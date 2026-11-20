/**
 * Reactive Auth Store (ESM)
 */

class AuthStore {
  constructor() {
    this.token = null;
    this.user = null;
    this.listeners = new Set();
    this.hydrateFromStorage();
  }

  hydrateFromStorage() {
    try {
      const storedToken = localStorage.getItem("vs_access_token") || sessionStorage.getItem("vs_access_token");
      const storedUser = localStorage.getItem("vs_user_profile") || sessionStorage.getItem("vs_user_profile");
      if (storedToken && storedUser) {
        this.token = storedToken;
        this.user = JSON.parse(storedUser);
      }
    } catch {}
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    this.listeners.forEach((listener) => listener());
  }

  getToken() {
    return this.token;
  }

  getUser() {
    return this.user;
  }

  isAuthenticated() {
    return Boolean(this.token);
  }

  hasRole(role) {
    return this.user?.role?.toLowerCase() === role?.toLowerCase();
  }

  setSession(tokenResponse) {
    this.token = tokenResponse.access_token;
    this.user = {
      id: tokenResponse.user_id,
      email: tokenResponse.email,
      username: tokenResponse.username,
      role: tokenResponse.role,
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

  updateToken(newToken, newTenantId, newRole) {
    this.token = newToken;
    if (this.user) {
      this.user.tenantId = newTenantId;
      if (newRole) this.user.role = newRole;
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

  logout() {
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

