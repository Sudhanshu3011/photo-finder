import { apiClient } from "./apiClient.js";

export const systemApi = {
  async checkHealth() {
    return await apiClient.get("/health", { skipAuth: true });
  },

  async checkS3Health() {
    return await apiClient.get("/health/s3", { skipAuth: true });
  },
};

