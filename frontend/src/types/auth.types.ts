/**
 * Authentication and Multi-Tenant Types
 * Derived from backend src/schemas/auth_schemas.py
 * Respects strict user-centric anti-slop guidelines.
 */

export type TenantRole = "owner" | "admin" | "editor" | "contributor" | "viewer";

export interface UserProfile {
  id: string;
  email: string;
  username: string;
  fullName?: string;
  avatarUrl?: string;
  role: TenantRole;
  tenantId: string;
  organizationName?: string;
  availableTenants?: TenantOption[];
}

export interface TenantOption {
  tenant_id: string;
  organization_name: string;
  role: string;
  photo_count?: number;
  initials?: string;
  theme_color?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  username: string;
  email: string;
  role: string;
  tenant_id: string;
  organization_name?: string;
}

export interface MultiTenantLoginResponse {
  status: "select_tenant";
  message: string;
  available_tenants: TenantOption[];
}

export type LoginResult = 
  | { type: "success"; data: TokenResponse }
  | { type: "disambiguation_required"; data: MultiTenantLoginResponse };

export interface LoginPayload {
  email: string;
  password: string;
  tenant_id?: string;
}

export interface SwitchTenantPayload {
  tenant_id: string;
}

export interface RegisterTenantPayload {
  username: string;
  email: string;
  password: string;
  organization_name: string;
  ignore_pending_invite?: boolean;
}

export interface InvitePreview {
  invite_id: string;
  tenant_id: string;
  organization_name: string;
  email: string;
  role: TenantRole;
  expires_at: string;
}

export interface AcceptInvitePayload {
  invite_token: string;
  username: string;
  password: string;
}

export interface AuthState {
  token: string | null;
  user: UserProfile | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
}

export interface WorkspaceState {
  currentTenantId: string | null;
  currentOrganizationName: string;
  currentRole: TenantRole | "Studio Owner" | "Contributor" | "Viewer";
  availableTenants: TenantOption[];
  isDisambiguating: boolean;
  pendingInviteCount: number;
}

