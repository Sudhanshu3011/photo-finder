import { apiClient } from "./apiClient";

export interface PhotoUploadItem {
  image_id: string;
  filename: string;
  s3_key?: string;
  thumbnail_url?: string;
  status: string;
  faces_detected?: number;
  face_ids?: string[];
  message?: string;
}

export interface BatchUploadResponse {
  job_id: string;
  total: number;
  successful: number;
  failed: number;
  items: PhotoUploadItem[];
}

export interface JobProgressResponse {
  job_id: string;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | string;
  total_images: number;
  processed_images: number;
  total_files?: number;
  processed_files?: number;
  current_stage?: string;
  logs: string[];
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FolderItem {
  folder_id: string;
  folder_name: string;
  description?: string;
  photo_count?: number;
  can_upload?: boolean;
  can_manage?: boolean;
  can_delete?: boolean;
  effective_access?: string;
}

export const uploadApi = {
  /**
   * Upload multiple photos in a single batch request (up to 50 photos)
   */
  async uploadBatch(
    files: File[],
    folderName: string = "general",
    useCelery: boolean = false
  ): Promise<BatchUploadResponse> {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file);
    });
    formData.append("folder_name", folderName);
    formData.append("use_celery", useCelery ? "true" : "false");

    return await apiClient.request<BatchUploadResponse>("/api/upload/batch", {
      method: "POST",
      body: formData,
    });
  },

  /**
   * Poll progress of an asynchronous batch ingestion job
   */
  async getJobProgress(jobId: string): Promise<JobProgressResponse> {
    try {
      return await apiClient.request<JobProgressResponse>(`/api/processing/jobs/${jobId}/progress`, {
        method: "GET",
      });
    } catch {
      return await apiClient.request<JobProgressResponse>(`/api/jobs/${jobId}`, {
        method: "GET",
      });
    }
  },

  /**
   * Fetch accessible folders / albums for the current user and workspace
   */
  async getFolders(canUpload?: boolean): Promise<FolderItem[]> {
    const url = canUpload !== undefined ? `/api/folders?can_upload=${canUpload}` : "/api/folders";
    return await apiClient.request<FolderItem[]>(url, {
      method: "GET",
    });
  },

  /**
   * Create a new folder/album
   */
  async createFolder(folderName: string, description?: string): Promise<FolderItem> {
    return await apiClient.request<FolderItem>("/api/folders", {
      method: "POST",
      body: JSON.stringify({
        folder_name: folderName,
        description: description || "",
      }),
    });
  },
};

