/**
 * Reactive Workspace Store
 * Manages Multi-Tenant Context, Workspace Switching, and Tenant Disambiguation.
 */

import { TenantOption } from "../types/auth.types";
import { authStore } from "./authStore";
import { authApi } from "../services/api/authApi";
import { apiClient } from "../services/api/apiClient";

export type WorkspaceListener = () => void;

class WorkspaceStore {
  private currentTenantId: string | null = null;
  private currentOrganizationName: string = "Workspace";
  private currentRole: string = "Viewer";
  private availableTenants: TenantOption[] = [];
  private isDisambiguating: boolean = false;
  private pendingInviteCount: number = 0;
  private listeners: Set<WorkspaceListener> = new Set();

  constructor() {
    this.wireApiClient();
    this.initDefaultWorkspaces();
  }

  private initDefaultWorkspaces(): void {
    const authUser = authStore.getUser();
    if (authUser && authUser.tenantId) {
      this.currentTenantId = authUser.tenantId;
      this.currentOrganizationName = authUser.organizationName || "Workspace";
      this.currentRole = authUser.role;
      this.availableTenants = [
        {
          tenant_id: authUser.tenantId,
          organization_name: authUser.organizationName || "Workspace",
          role: authUser.role,
        }
      ];
      this.fetchGenuineWorkspaces();
    } else {
      this.currentTenantId = null;
      this.currentOrganizationName = "Workspace";
      this.currentRole = "Viewer";
      this.availableTenants = [];
    }

    // Reactively synchronize tenant context when authStore session hydrates or changes
    authStore.subscribe(() => {
      const u = authStore.getUser();
      if (u && u.tenantId) {
        this.currentTenantId = u.tenantId;
        if (u.role) this.currentRole = u.role;
        this.currentOrganizationName = u.organizationName || "Workspace";
        if (!this.availableTenants.some(t => t.tenant_id === u.tenantId)) {
          this.availableTenants = [
            {
              tenant_id: u.tenantId,
              organization_name: u.organizationName || "Workspace",
              role: u.role,
            }
          ];
        }
        this.fetchGenuineWorkspaces();
      } else {
        this.currentTenantId = null;
        this.currentOrganizationName = "Workspace";
        this.currentRole = "Viewer";
        this.availableTenants = [];
        this.notify();
      }
    });
  }

  public async fetchGenuineWorkspaces(): Promise<void> {
    if (!authStore.isAuthenticated()) return;
    try {
      const workspaces = await authApi.getUserWorkspaces();
      if (Array.isArray(workspaces) && workspaces.length > 0) {
        this.availableTenants = workspaces;
        const current = workspaces.find(w => w.tenant_id === this.currentTenantId);
        if (current) {
          this.currentOrganizationName = current.organization_name;
          this.currentRole = current.role as any;
        }
        this.notify();
      }
    } catch {
      // In offline or fallback, retain primary tenant
    }
  }

  public setAvailableTenants(tenants: TenantOption[]): void {
    this.availableTenants = tenants;
    this.notify();
  }

  private wireApiClient(): void {
    apiClient.configure({
      getToken: () => authStore.getToken(),
      getTenantId: () => this.currentTenantId || authStore.getUser()?.tenantId || null,
      onUnauthorized: () => {
        if (authStore.isAuthenticated()) {
          authStore.logout();
        }
      },
    });
  }

  public subscribe(listener: WorkspaceListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    this.listeners.forEach(listener => listener());
  }

  public getCurrentTenantId(): string | null {
    return this.currentTenantId;
  }

  public getCurrentOrganizationName(): string {
    return this.currentOrganizationName;
  }

  public getCurrentRole(): string {
    return this.currentRole;
  }

  public getAvailableTenants(): TenantOption[] {
    return this.availableTenants;
  }

  public getPendingInviteCount(): number {
    return this.pendingInviteCount;
  }

  public isDisambiguationRequired(): boolean {
    return this.isDisambiguating;
  }

  public setDisambiguation(tenants: TenantOption[]): void {
    this.availableTenants = tenants;
    this.isDisambiguating = true;
    this.notify();
  }

  public setCurrentWorkspace(tenantId: string, orgName?: string, role?: string): void {
    this.currentTenantId = tenantId;
    if (orgName) this.currentOrganizationName = orgName;
    if (role) this.currentRole = role;
    this.isDisambiguating = false;
    this.notify();
  }

  public async switchWorkspace(targetTenantId: string): Promise<void> {
    const target = this.availableTenants.find(t => t.tenant_id === targetTenantId);
    if (!target) return;

    try {
      // If user has a live token, call the backend switch-tenant endpoint
      if (authStore.getToken()) {
        const tokenRes = await authApi.switchTenant(targetTenantId);
        authStore.updateToken(tokenRes.access_token, tokenRes.tenant_id, tokenRes.role);
      }
    } catch {
      // If offline/preview, proceed with optimistic client switch
    }

    this.currentTenantId = target.tenant_id;
    this.currentOrganizationName = target.organization_name;
    this.currentRole = target.role;
    this.isDisambiguating = false;

    // Trigger notification to re-fetch albums and reload UI context
    this.notify();
  }
}

export const workspaceStore = new WorkspaceStore();

