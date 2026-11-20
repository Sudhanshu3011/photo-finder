import { apiClient } from "./apiClient.js";

export class SearchApiService {
  /**
   * Search photo gallery using a query image file (Face or Scene)
   */
  async searchByImage(file, options = {}) {
    const formData = new FormData();
    if (file) {
      formData.append("file", file, file.name || "query.jpg");
    }
    if (options.imageUrl) {
      formData.append("image_url", options.imageUrl);
    }

    if (options.folderName && options.folderName !== "all") {
      formData.append("folder_name", options.folderName);
    }

    const params = {};
    if (options.topK !== undefined) params.top_k = options.topK;
    if (options.threshold !== undefined) params.threshold = options.threshold;

    return apiClient.post("/search/image", formData, { params });
  }

  /**
   * Multi-angle facial similarity search (front, left profile, right profile)
   */
  async searchByMultiAngle(files = {}, options = {}) {
    const formData = new FormData();
    if (files.front) formData.append("front_file", files.front, files.front.name);
    if (files.left) formData.append("left_file", files.left, files.left.name);
    if (files.right) formData.append("right_file", files.right, files.right.name);

    if (options.folderName && options.folderName !== "all") {
      formData.append("folder_name", options.folderName);
    }

    const params = {};
    if (options.topK !== undefined) params.top_k = options.topK;
    if (options.threshold !== undefined) params.threshold = options.threshold;

    return apiClient.post("/search/multi-angle", formData, { params });
  }
}

export const searchApi = new SearchApiService();

