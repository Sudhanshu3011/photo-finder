/**
 * Central HTTP API Client
 * Enforces JWT Authorization and X-Tenant-ID Header Injection
 * Adheres to auth-implementation-patterns and saas-multi-tenant security rules.
 */

export interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
  skipAuth?: boolean;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public data: any
  ) {
    super(`API Error ${status} (${statusText}): ${JSON.stringify(data)}`);
    this.name = "ApiError";
  }
}

class ApiClient {
  private baseUrl: string = "/api";
  private tokenGetter: (() => string | null) | null = null;
  private tenantIdGetter: (() => string | null) | null = null;
  private unauthorizedHandler: (() => void) | null = null;
  private isHandlingUnauthorized: boolean = false;
  private inFlightRequests: Map<string, Promise<any>> = new Map();

  public configure(config: {
    baseUrl?: string;
    getToken: () => string | null;
    getTenantId: () => string | null;
    onUnauthorized: () => void;
  }): void {
    if (config.baseUrl) this.baseUrl = config.baseUrl;
    this.tokenGetter = config.getToken;
    this.tenantIdGetter = config.getTenantId;
    this.unauthorizedHandler = config.onUnauthorized;
  }

  private buildHeaders(options: RequestOptions): Headers {
    const headers = new Headers(options.headers || {});

    // Set JSON content type by default unless body is FormData
    if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    // Attach JWT Bearer Token if available and not skipped
    if (!options.skipAuth) {
      const token = this.tokenGetter ? this.tokenGetter() : (typeof localStorage !== "undefined" ? localStorage.getItem("vs_access_token") : null);
      if (token && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
      }
    }

    // Attach X-Tenant-ID Multi-Tenant Isolation Header
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

  public async request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
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
      return this.inFlightRequests.get(dedupeKey)! as Promise<T>;
    }

    const executeRequest = async (): Promise<T> => {
      const headers = this.buildHeaders(options);

      try {
        const response = await fetch(url.toString(), {
          ...options,
          headers,
        });

        if (response.status === 401) {
          const sentAuth = headers.has("Authorization");
          const isAuthEndpoint = finalPath.includes("/auth/login") || finalPath.includes("/auth/register");
          if (sentAuth && !isAuthEndpoint && this.unauthorizedHandler && !this.isHandlingUnauthorized) {
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
          let errorData: any;
          try {
            errorData = await response.json();
          } catch {
            errorData = await response.text();
          }
          throw new ApiError(response.status, response.statusText, errorData);
        }

        // Check if response has content
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
          return (await response.json()) as T;
        }

        return (await response.text()) as unknown as T;
      } catch (err: any) {
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

  public get<T>(endpoint: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: "GET" });
  }

  public post<T>(endpoint: string, body?: any, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
  }

  public patch<T>(endpoint: string, body?: any, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "PATCH",
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
  }

  public delete<T>(endpoint: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: "DELETE" });
  }
}

export const apiClient = new ApiClient();

