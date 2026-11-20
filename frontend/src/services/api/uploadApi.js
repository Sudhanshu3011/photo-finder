import { apiClient } from "./apiClient.js";

export const uploadApi = {
  /**
   * Upload multiple photos in a single batch request (up to 50 photos)
   */
  async uploadBatch(files, folderName = "general", useCelery = false) {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file);
    });
    formData.append("folder_name", folderName);
    formData.append("use_celery", useCelery ? "true" : "false");

    return await apiClient.request("/api/upload/batch", {
      method: "POST",
      body: formData,
    });
  },

  /**
   * Poll progress of an asynchronous batch ingestion job
   */
  async getJobProgress(jobId) {
    try {
      return await apiClient.request(`/api/processing/jobs/${jobId}/progress`, {
        method: "GET",
      });
    } catch {
      return await apiClient.request(`/api/jobs/${jobId}`, {
        method: "GET",
      });
    }
  },

  /**
   * Fetch accessible folders / albums for the current user and workspace
   */
  async getFolders(canUpload) {
    const url = canUpload !== undefined ? `/api/folders?can_upload=${canUpload}` : "/api/folders";
    return await apiClient.request(url, {
      method: "GET",
    });
  },

  /**
   * Create a new folder/album
   */
  async createFolder(folderName, description = "") {
    return await apiClient.request("/api/folders", {
      method: "POST",
      body: JSON.stringify({
        folder_name: folderName,
        description: description,
      }),
    });
  },
};

