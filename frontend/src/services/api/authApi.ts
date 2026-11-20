/**
 * Auth & Multi-Tenant API Service
 * Maps cleanly to src/api/auth_routes.py endpoints.
 */

import { apiClient } from "./apiClient";
import {
  LoginPayload,
  LoginResult,
  TokenResponse,
  MultiTenantLoginResponse,
  SwitchTenantPayload,
  RegisterTenantPayload,
  InvitePreview,
  AcceptInvitePayload,
  UserProfile,
  TenantOption,
} from "../../types/auth.types";

export const authApi = {
  /**
   * Unified Authentication
   * Handles single-tenant immediate token issuance or multi-tenant disambiguation options.
   */
  async login(payload: LoginPayload): Promise<LoginResult> {
    const response = await apiClient.post<TokenResponse | MultiTenantLoginResponse>(
      "/auth/login",
      payload,
      { skipAuth: true }
    );

    if ("status" in response && response.status === "select_tenant") {
      return {
        type: "disambiguation_required",
        data: response as MultiTenantLoginResponse,
      };
    }

    return {
      type: "success",
      data: response as TokenResponse,
    };
  },

  /**
   * Switch Active Workspace Session
   * Issues a refreshed JWT scoped to the new tenant.
   */
  async switchTenant(targetTenantId: string): Promise<TokenResponse> {
    const payload: SwitchTenantPayload = { tenant_id: targetTenantId };
    return await apiClient.post<TokenResponse>("/auth/switch-tenant", payload);
  },

  /**
   * Register a new Tenant Organization
   */
  async registerTenant(payload: RegisterTenantPayload): Promise<TokenResponse> {
    return await apiClient.post<TokenResponse>("/auth/register-tenant", payload, { skipAuth: true });
  },

  /**
   * Preview Locked Invitation details
   */
  async getInvitePreview(inviteToken: string): Promise<InvitePreview> {
    return await apiClient.get<InvitePreview>("/auth/invite-preview", {
      params: { token: inviteToken },
      skipAuth: true,
    });
  },

  /**
   * Accept locked invitation
   */
  async acceptInvite(payload: AcceptInvitePayload): Promise<TokenResponse> {
    return await apiClient.post<TokenResponse>("/auth/accept-invite", payload, { skipAuth: true });
  },

  /**
   * Get Current Authenticated Profile
   */
  async getCurrentProfile(): Promise<UserProfile> {
    return await apiClient.get<UserProfile>("/auth/me");
  },

  /**
   * Get Genuine Workspaces of Authenticated User
   */
  async getUserWorkspaces(): Promise<TenantOption[]> {
    return await apiClient.get<TenantOption[]>("/auth/workspaces");
  },
};

