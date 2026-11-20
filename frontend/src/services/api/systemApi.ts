/**
 * System Health & Connectivity API Service
 * Interacts with FastAPI /api/health and /api/health/s3
 */

import { apiClient } from "./apiClient";

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  timestamp: string;
}

export interface S3HealthResponse {
  status: string;
  storage: string;
  bucket: string;
  region: string;
  accessible: boolean;
  latency_ms: number;
  error?: string | null;
  timestamp: string;
}

export const systemApi = {
  /**
   * Probe backend system liveness and readiness
   */
  async checkHealth(): Promise<HealthResponse> {
    return await apiClient.get<HealthResponse>("/health", { skipAuth: true });
  },

  /**
   * Check S3 Storage status
   */
  async checkS3Health(): Promise<S3HealthResponse> {
    return await apiClient.get<S3HealthResponse>("/health/s3", { skipAuth: true });
  },
};

