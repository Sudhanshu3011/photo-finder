import { apiClient } from "./apiClient.js";

export class PeopleApiService {
  /**
   * Fetch all identified face clusters (people gallery), optionally filtered by collection/folder
   */
  async getClusters(folderName) {
    const params = {};
    if (folderName && folderName !== "all") {
      params.folder_name = folderName;
    }
    return apiClient.get("/clusters", { params });
  }

  /**
   * Rename an identified person / cluster
   */
  async renameCluster(clusterId, personName) {
    return apiClient.patch(`/clusters/${encodeURIComponent(clusterId)}`, {
      person_name: personName.trim(),
    });
  }

  /**
   * Trigger automatic face clustering & medoid identification
   */
  async triggerClustering(folderName) {
    const params = {};
    if (folderName && folderName !== "all") {
      params.folder_name = folderName;
    }
    return apiClient.post("/clusters/generate", {}, { params });
  }

  /**
   * Check whether new unclustered photos are ready for clustering
   */
  async getClusterStatus(folderName) {
    return apiClient.get("/clusters/status", {
      params: { folder_name: folderName },
    });
  }
}

export const peopleApi = new PeopleApiService();

