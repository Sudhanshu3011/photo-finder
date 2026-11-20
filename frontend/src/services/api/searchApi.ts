import { apiClient } from "./apiClient";

export interface MatchItem {
  image_id: string;
  score: number;
  bbox?: [number, number, number, number] | null;
  person_name?: string | null;
  cluster_id?: string | null;
  thumbnail_url?: string | null;
  cloud_url?: string | null;
  metadata?: Record<string, any>;
}

export interface SearchResponse {
  query_type: string;
  total_matches: number;
  results: MatchItem[];
}

export interface SearchOptions {
  folderName?: string;
  topK?: number;
  threshold?: number;
  imageUrl?: string;
}

export class SearchApiService {
  /**
   * Search photo gallery using a query image file or image URL (Face or Scene)
   */
  public async searchByImage(
    file?: File | Blob | null,
    options: SearchOptions = {}
  ): Promise<SearchResponse> {
    const formData = new FormData();
    if (file) {
      formData.append("file", file, (file as File).name || "query.jpg");
    }
    if (options.imageUrl) {
      formData.append("image_url", options.imageUrl);
    }

    if (options.folderName && options.folderName !== "all") {
      formData.append("folder_name", options.folderName);
    }

    const params: Record<string, string | number> = {};
    if (options.topK !== undefined) params.top_k = options.topK;
    if (options.threshold !== undefined) params.threshold = options.threshold;

    return apiClient.post<SearchResponse>("/search/image", formData, { params });
  }

  /**
   * Multi-angle facial similarity search (front, left profile, right profile)
   */
  public async searchByMultiAngle(
    files: { front?: File; left?: File; right?: File },
    options: SearchOptions = {}
  ): Promise<SearchResponse> {
    const formData = new FormData();
    if (files.front) formData.append("front_file", files.front, files.front.name);
    if (files.left) formData.append("left_file", files.left, files.left.name);
    if (files.right) formData.append("right_file", files.right, files.right.name);

    if (options.folderName && options.folderName !== "all") {
      formData.append("folder_name", options.folderName);
    }

    const params: Record<string, string | number> = {};
    if (options.topK !== undefined) params.top_k = options.topK;
    if (options.threshold !== undefined) params.threshold = options.threshold;

    return apiClient.post<SearchResponse>("/search/multi-angle", formData, { params });
  }
}

export const searchApi = new SearchApiService();

