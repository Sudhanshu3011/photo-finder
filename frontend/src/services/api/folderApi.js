import { apiClient } from "./apiClient.js";

export const folderApi = {
  /**
   * Fetch all folders / albums for the current user and organization
   */
  async getFolders(canUpload) {
    const url = canUpload !== undefined ? `/api/folders?can_upload=${canUpload}` : "/api/folders";
    return await apiClient.request(url, {
      method: "GET",
    });
  },

  /**
   * Fetch a single folder's details
   */
  async getFolder(folderId) {
    return await apiClient.request(`/api/folders/${folderId}`, {
      method: "GET",
    });
  },

  /**
   * Create a new collection / album
   */
  async createFolder(folderName, description = "", visibility = "restricted") {
    return await apiClient.request("/api/folders", {
      method: "POST",
      body: JSON.stringify({
        folder_name: folderName,
        description: description,
        visibility: visibility,
      }),
    });
  },

  /**
   * Delete an album
   */
  async deleteFolder(folderId) {
    return await apiClient.request(`/api/folders/${folderId}`, {
      method: "DELETE",
    });
  },

  /**
   * List members with explicit permissions for an album
   */
  async getFolderMembers(folderId) {
    return await apiClient.request(`/api/folders/${folderId}/members`, {
      method: "GET",
    });
  },

  /**
   * List all registered members of the current tenant/organization
   */
  async getTenantMembers() {
    return await apiClient.request("/api/tenant/members", {
      method: "GET",
    });
  },

  /**
   * Bulk update member access grants for an album in plain English
   */
  async updateFolderAccessBulk(folderId, grants) {
    return await apiClient.request(`/api/folders/${folderId}/access/bulk`, {
      method: "POST",
      body: JSON.stringify({ grants }),
    });
  },

  /**
   * Revoke a single member's access to an album
   */
  async revokeMemberAccess(folderId, userId) {
    return await apiClient.request(`/api/folders/${folderId}/access/${userId}`, {
      method: "DELETE",
    });
  },
};
