import { apiClient } from "./apiClient";

export interface FolderDto {
  folder_id: string;
  folder_name: string;
  description?: string;
  visibility: "tenant_wide" | "restricted" | string;
  photo_count: number;
  effective_access: string;
  can_upload: boolean;
  can_delete: boolean;
  can_manage: boolean;
  created_by?: string;
  created_at: string;
  cover_url?: string;
}

export interface FolderMemberAccess {
  user_id: string;
  username: string;
  email: string;
  tenant_role: string;
  access_level: string;
  granted_by?: string;
  created_at: string;
}

export interface TenantMemberDto {
  user_id: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface MemberGrantInput {
  user_id: string;
  can_view: boolean;
  can_upload: boolean;
  can_manage: boolean;
  access_level?: string;
}

export const folderApi = {
  /**
   * Fetch all folders / albums for the current user and organization
   */
  async getFolders(canUpload?: boolean): Promise<FolderDto[]> {
    const url = canUpload !== undefined ? `/api/folders?can_upload=${canUpload}` : "/api/folders";
    return await apiClient.request<FolderDto[]>(url, {
      method: "GET",
    });
  },

  /**
   * Fetch a single folder's details
   */
  async getFolder(folderId: string): Promise<FolderDto> {
    return await apiClient.request<FolderDto>(`/api/folders/${folderId}`, {
      method: "GET",
    });
  },

  /**
   * Create a new collection / album
   */
  async createFolder(
    folderName: string,
    description?: string,
    visibility: "tenant_wide" | "restricted" = "restricted"
  ): Promise<FolderDto> {
    return await apiClient.request<FolderDto>("/api/folders", {
      method: "POST",
      body: JSON.stringify({
        folder_name: folderName,
        description: description || "",
        visibility,
      }),
    });
  },

  /**
   * Delete an album
   */
  async deleteFolder(folderId: string): Promise<{ status: string; message: string }> {
    return await apiClient.request<{ status: string; message: string }>(`/api/folders/${folderId}`, {
      method: "DELETE",
    });
  },

  /**
   * List members with explicit permissions for an album
   */
  async getFolderMembers(folderId: string): Promise<FolderMemberAccess[]> {
    return await apiClient.request<FolderMemberAccess[]>(`/api/folders/${folderId}/members`, {
      method: "GET",
    });
  },

  /**
   * List all registered members of the current tenant/organization
   */
  async getTenantMembers(): Promise<TenantMemberDto[]> {
    return await apiClient.request<TenantMemberDto[]>("/api/tenant/members", {
      method: "GET",
    });
  },

  /**
   * Bulk update member access grants for an album in plain English
   */
  async updateFolderAccessBulk(
    folderId: string,
    grants: MemberGrantInput[]
  ): Promise<{ status: string; message: string; updated_count: number }> {
    return await apiClient.request<{ status: string; message: string; updated_count: number }>(
      `/api/folders/${folderId}/access/bulk`,
      {
        method: "POST",
        body: JSON.stringify({ grants }),
      }
    );
  },

  /**
   * Revoke a single member's access to an album
   */
  async revokeMemberAccess(
    folderId: string,
    userId: string
  ): Promise<{ status: string; message: string }> {
    return await apiClient.request<{ status: string; message: string }>(
      `/api/folders/${folderId}/access/${userId}`,
      {
        method: "DELETE",
      }
    );
  },
};
