/**
 * Reactive Auth Store
 * Manages JWT tokens, authenticated user state, and session lifecycle.
 */

import { UserProfile, TokenResponse } from "../types/auth.types";

export type AuthListener = () => void;

class AuthStore {
  private token: string | null = null;
  private user: UserProfile | null = null;
  private listeners: Set<AuthListener> = new Set();
  public isInitialized = false;

  constructor() {
    this.hydrateFromStorage();
  }

  private hydrateFromStorage(): void {
    try {
      const storedToken = localStorage.getItem("vs_access_token") || sessionStorage.getItem("vs_access_token");
      const storedUser = localStorage.getItem("vs_user_profile") || sessionStorage.getItem("vs_user_profile");
      if (storedToken && storedUser) {
        this.token = storedToken;
        this.user = JSON.parse(storedUser);
      }
    } catch {
      // Storage unavailable or disabled
    }
    this.isInitialized = true;
  }

  public subscribe(listener: AuthListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    this.listeners.forEach((listener) => listener());
  }

  public getToken(): string | null {
    return this.token;
  }

  public getUser(): UserProfile | null {
    return this.user;
  }

  public isAuthenticated(): boolean {
    return Boolean(this.token);
  }

  public hasRole(role: string): boolean {
    return this.user?.role?.toLowerCase() === role.toLowerCase();
  }

  public setSession(tokenResponse: TokenResponse): void {
    this.token = tokenResponse.access_token;
    this.user = {
      id: tokenResponse.user_id,
      email: tokenResponse.email,
      username: tokenResponse.username,
      role: tokenResponse.role as any,
      tenantId: tokenResponse.tenant_id,
      organizationName: tokenResponse.organization_name || "Workspace",
    };

    try {
      localStorage.setItem("vs_access_token", this.token);
      localStorage.setItem("vs_user_profile", JSON.stringify(this.user));
      sessionStorage.setItem("vs_access_token", this.token);
      sessionStorage.setItem("vs_user_profile", JSON.stringify(this.user));
    } catch {}

    this.notify();
  }

  public updateToken(newToken: string, newTenantId: string, newRole?: string): void {
    this.token = newToken;
    if (this.user) {
      this.user.tenantId = newTenantId;
      if (newRole) this.user.role = newRole as any;
      try {
        localStorage.setItem("vs_user_profile", JSON.stringify(this.user));
        sessionStorage.setItem("vs_user_profile", JSON.stringify(this.user));
      } catch {}
    }

    try {
      localStorage.setItem("vs_access_token", newToken);
      sessionStorage.setItem("vs_access_token", newToken);
    } catch {}

    this.notify();
  }

  public logout(): void {
    if (!this.token && !this.user) {
      return;
    }
    this.token = null;
    this.user = null;

    try {
      localStorage.removeItem("vs_access_token");
      localStorage.removeItem("vs_user_profile");
      sessionStorage.removeItem("vs_access_token");
      sessionStorage.removeItem("vs_user_profile");
    } catch {}

    this.notify();
  }
}

export const authStore = new AuthStore();

