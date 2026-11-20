import { apiClient } from "./apiClient";

export interface FaceCluster {
  cluster_id: string;
  person_name: string;
  face_count: number;
  folder?: string | null;
  medoid_image_url?: string | null;
  sample_crop_urls?: string[];
  created_at?: string | null;
}

export interface ClusteringTriggerResponse {
  status: string;
  clusters_found: number;
  total_faces: number;
  message: string;
}

export interface ClusterStatusResponse {
  folder_name: string;
  total_photos: number;
  last_clustered_count: number;
  new_photos_since_last_cluster: number;
  threshold: number;
  ready_for_clustering: boolean;
}

export class PeopleApiService {
  /**
   * Fetch all identified face clusters (people gallery), optionally filtered by collection/folder
   */
  public async getClusters(folderName?: string): Promise<FaceCluster[]> {
    const params: Record<string, string> = {};
    if (folderName && folderName !== "all") {
      params.folder_name = folderName;
    }
    return apiClient.get<FaceCluster[]>("/clusters", { params });
  }

  /**
   * Rename an identified person / cluster
   */
  public async renameCluster(clusterId: string, personName: string): Promise<FaceCluster> {
    return apiClient.patch<FaceCluster>(`/clusters/${encodeURIComponent(clusterId)}`, {
      person_name: personName.trim(),
    });
  }

  /**
   * Trigger automatic face clustering & medoid identification
   */
  public async triggerClustering(folderName?: string): Promise<ClusteringTriggerResponse> {
    const params: Record<string, string> = {};
    if (folderName && folderName !== "all") {
      params.folder_name = folderName;
    }
    return apiClient.post<ClusteringTriggerResponse>("/clusters/generate", {}, { params });
  }

  /**
   * Check whether new unclustered photos are ready for clustering
   */
  public async getClusterStatus(folderName: string): Promise<ClusterStatusResponse> {
    return apiClient.get<ClusterStatusResponse>("/clusters/status", {
      params: { folder_name: folderName },
    });
  }
}

export const peopleApi = new PeopleApiService();

