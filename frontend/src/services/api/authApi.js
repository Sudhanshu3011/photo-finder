import { apiClient } from "./apiClient.js";

export const authApi = {
  async login(payload) {
    const response = await apiClient.post("/auth/login", payload, { skipAuth: true });
    if (response && response.status === "select_tenant") {
      return {
        type: "disambiguation_required",
        data: response,
      };
    }
    return {
      type: "success",
      data: response,
    };
  },

  async switchTenant(targetTenantId) {
    return await apiClient.post("/auth/switch-tenant", { tenant_id: targetTenantId });
  },

  async registerTenant(payload) {
    return await apiClient.post("/auth/register-tenant", payload, { skipAuth: true });
  },

  async previewInvite(token) {
    return await apiClient.get(`/auth/invite-preview?token=${encodeURIComponent(token)}`, { skipAuth: true });
  },

  async acceptInvite(payload) {
    return await apiClient.post("/auth/accept-invite", payload, { skipAuth: true });
  },

  async getCurrentProfile() {
    return await apiClient.get("/auth/me");
  },

  async getProfile() {
    return await apiClient.get("/auth/me");
  },

  async getUserWorkspaces() {
    return await apiClient.get("/auth/workspaces");
  },
};

