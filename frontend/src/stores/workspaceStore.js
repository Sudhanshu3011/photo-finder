/**
 * Reactive Workspace Store (ESM)
 */

import { authStore } from "./authStore.js";
import { apiClient } from "../services/api/apiClient.js";
import { authApi } from "../services/api/authApi.js";

class WorkspaceStore {
  constructor() {
    this.currentTenantId = null;
    this.currentOrganizationName = "Workspace";
    this.currentRole = "Viewer";
    this.availableTenants = [];
    this.isDisambiguating = false;
    this.pendingInviteCount = 0;
    this.listeners = new Set();

    this.wireApiClient();
    this.initDefaultWorkspaces();
  }

  wireApiClient() {
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

  initDefaultWorkspaces() {
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

  async fetchGenuineWorkspaces() {
    if (!authStore.isAuthenticated()) return;
    try {
      const workspaces = await authApi.getUserWorkspaces();
      if (Array.isArray(workspaces) && workspaces.length > 0) {
        this.availableTenants = workspaces;
        const current = workspaces.find(w => w.tenant_id === this.currentTenantId);
        if (current) {
          this.currentOrganizationName = current.organization_name;
          this.currentRole = current.role;
        }
        this.notify();
      }
    } catch {
      // In offline or fallback, retain primary tenant
    }
  }

  setAvailableTenants(tenants) {
    this.availableTenants = tenants;
    this.notify();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    this.listeners.forEach(listener => listener());
  }

  getCurrentTenantId() {
    return this.currentTenantId;
  }

  getCurrentOrganizationName() {
    return this.currentOrganizationName;
  }

  getCurrentRole() {
    return this.currentRole;
  }

  getAvailableTenants() {
    return this.availableTenants;
  }

  getPendingInviteCount() {
    return this.pendingInviteCount;
  }

  setCurrentWorkspace(tenantId, orgName, role) {
    this.currentTenantId = tenantId;
    if (orgName) this.currentOrganizationName = orgName;
    if (role) this.currentRole = role;
    this.isDisambiguating = false;
    this.notify();
  }

  async switchWorkspace(targetTenantId) {
    const target = this.availableTenants.find(t => t.tenant_id === targetTenantId);
    if (!target) return;

    try {
      if (authStore.getToken()) {
        const tokenRes = await authApi.switchTenant(targetTenantId);
        authStore.updateToken(tokenRes.access_token, tokenRes.tenant_id, tokenRes.role);
      }
    } catch (err) {
      console.warn("Backend switch-tenant failed, proceeding with client selection:", err);
    }

    this.currentTenantId = target.tenant_id;
    this.currentOrganizationName = target.organization_name;
    this.currentRole = target.role;
    this.isDisambiguating = false;

    this.notify();
  }
}

export const workspaceStore = new WorkspaceStore();

