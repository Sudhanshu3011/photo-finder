/**
 * Tenant & Team Collaboration API Service (ESM)
 */

import { apiClient } from "./apiClient.js";

export const tenantApi = {
  async inviteMember(payload) {
    return await apiClient.request("/api/tenant/invites", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async getMembers(limit = 50, offset = 0) {
    return await apiClient.request("/api/tenant/members", {
      method: "GET",
      params: { limit, offset },
    });
  },

  async updateMemberRole(userId, role) {
    return await apiClient.request(`/api/tenant/members/${userId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    });
  },

  async removeMember(userId) {
    return await apiClient.request(`/api/tenant/members/${userId}`, {
      method: "DELETE",
    });
  },
};

