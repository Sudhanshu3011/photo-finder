/**
 * Tenant & Team Collaboration API Service
 * Maps cleanly to src/api/tenant_routes.py endpoints.
 */

import { apiClient } from "./apiClient";

export interface TenantInvitePayload {
  email: string;
  role: "admin" | "contributor" | "viewer" | string;
  initial_folder_ids?: string[];
  initial_access_level?: "manager" | "uploader" | "viewer" | string;
}

export interface TenantInviteResponse {
  invite_id: string;
  email: string;
  role: string;
  token: string;
  invite_link: string;
  expires_at: string;
  created_at: string;
}

export interface TenantMemberItem {
  user_id: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
  last_seen?: string;
}

export const tenantApi = {
  /**
   * Send an invitation to join the organization with optional pre-granted folders
   */
  async inviteMember(payload: TenantInvitePayload): Promise<TenantInviteResponse> {
    return await apiClient.request<TenantInviteResponse>("/api/tenant/invites", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * Fetch organization members
   */
  async getMembers(limit: number = 50, offset: number = 0): Promise<TenantMemberItem[]> {
    return await apiClient.request<TenantMemberItem[]>("/api/tenant/members", {
      method: "GET",
      params: { limit, offset },
    });
  },

  /**
   * Update an organization member's role
   */
  async updateMemberRole(userId: string, role: string): Promise<{ status: string; user_id: string; new_role: string }> {
    return await apiClient.request<{ status: string; user_id: string; new_role: string }>(`/api/tenant/members/${userId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    });
  },

  /**
   * Remove a member from the organization
   */
  async removeMember(userId: string): Promise<{ status: string; message: string }> {
    return await apiClient.request<{ status: string; message: string }>(`/api/tenant/members/${userId}`, {
      method: "DELETE",
    });
  },
};

