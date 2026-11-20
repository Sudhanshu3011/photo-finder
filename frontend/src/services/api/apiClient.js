export class ApiError extends Error {
  constructor(status, statusText, data) {
    super(`API Error ${status} (${statusText}): ${JSON.stringify(data)}`);
    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
    this.data = data;
  }
}

class ApiClient {
  constructor() {
    this.baseUrl = "/api";
    this.tokenGetter = null;
    this.tenantIdGetter = null;
    this.unauthorizedHandler = null;
    this.isHandlingUnauthorized = false;
    this.inFlightRequests = new Map();
  }

  configure(config) {
    if (config.baseUrl) this.baseUrl = config.baseUrl;
    this.tokenGetter = config.getToken;
    this.tenantIdGetter = config.getTenantId;
    this.unauthorizedHandler = config.onUnauthorized;
  }

  buildHeaders(options) {
    const headers = new Headers(options.headers || {});

    if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    if (!options.skipAuth) {
      const token = this.tokenGetter ? this.tokenGetter() : (typeof localStorage !== "undefined" ? localStorage.getItem("vs_access_token") : null);
      if (token && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
      }
    }

    const tenantId = this.tenantIdGetter ? this.tenantIdGetter() : null;
    if (tenantId && !headers.has("X-Tenant-ID")) {
      headers.set("X-Tenant-ID", tenantId);
    } else if (!headers.has("X-Tenant-ID") && typeof localStorage !== "undefined") {
      try {
        const storedUser = localStorage.getItem("vs_user_profile");
        if (storedUser) {
          const parsed = JSON.parse(storedUser);
          if (parsed?.tenantId) {
            headers.set("X-Tenant-ID", parsed.tenantId);
          }
        }
      } catch {}
    }

    return headers;
  }

  async request(endpoint, options = {}) {
    let finalPath = endpoint;
    if (!endpoint.startsWith("http")) {
      if (endpoint.startsWith("/api/")) {
        finalPath = endpoint;
      } else {
        const cleanBase = this.baseUrl.endsWith("/") ? this.baseUrl.slice(0, -1) : this.baseUrl;
        const cleanEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
        finalPath = `${cleanBase}${cleanEndpoint}`;
      }
    }

    const url = new URL(finalPath, window.location.origin);

    if (options.params) {
      Object.entries(options.params).forEach(([key, val]) => {
        if (val !== undefined && val !== null) {
          url.searchParams.append(key, String(val));
        }
      });
    }

    const method = (options.method || "GET").toUpperCase();
    const dedupeKey = method === "GET" ? `${method}:${url.toString()}` : null;
    if (dedupeKey && this.inFlightRequests.has(dedupeKey)) {
      return this.inFlightRequests.get(dedupeKey);
    }

    const executeRequest = async () => {
      const headers = this.buildHeaders(options);

      try {
        const response = await fetch(url.toString(), {
          ...options,
          headers,
        });

        if (response.status === 401 && this.unauthorizedHandler) {
          const sentAuth = headers.has("Authorization");
          const isAuthEndpoint = finalPath.includes("/auth/login") || finalPath.includes("/auth/register");
          if (sentAuth && !isAuthEndpoint && !this.isHandlingUnauthorized) {
            this.isHandlingUnauthorized = true;
            try {
              this.unauthorizedHandler();
            } catch (e) {
              console.error("Error in onUnauthorized handler:", e);
            } finally {
              setTimeout(() => {
                this.isHandlingUnauthorized = false;
              }, 1000);
            }
          }
        }

        if (!response.ok) {
          let errorData;
          try {
            errorData = await response.json();
          } catch {
            errorData = await response.text();
          }
          throw new ApiError(response.status, response.statusText, errorData);
        }

        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
          return await response.json();
        }

        return await response.text();
      } catch (err) {
        if (err instanceof ApiError) throw err;
        throw new ApiError(0, "Network Connection Failed", { message: err?.message || "Unknown Network Error" });
      }
    };

    if (dedupeKey) {
      const promise = executeRequest().finally(() => {
        this.inFlightRequests.delete(dedupeKey);
      });
      this.inFlightRequests.set(dedupeKey, promise);
      return promise;
    }

    return executeRequest();
  }

  get(endpoint, options) {
    return this.request(endpoint, { ...options, method: "GET" });
  }

  post(endpoint, body, options) {
    return this.request(endpoint, {
      ...options,
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
  }

  patch(endpoint, body, options) {
    return this.request(endpoint, {
      ...options,
      method: "PATCH",
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
  }

  delete(endpoint, options) {
    return this.request(endpoint, { ...options, method: "DELETE" });
  }
}

export const apiClient = new ApiClient();

