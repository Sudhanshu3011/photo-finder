/**
 * AuthModal Component — Sign In & Sign Up (Create Studio)
 * Follows Elementum Editorial design, WCAG 2.2 AA accessibility, and anti-slop rules.
 * Integrates directly with FastAPI backend /api/auth endpoints.
 */

import { renderHighlighterPill } from "../../components/primitives/HighlighterPill";
import { renderButtonPill } from "../../components/primitives/ButtonPill";
import { TenantOption } from "../../types/auth.types";

export type AuthMode = "signin" | "signup" | "disambiguate";

export interface AuthModalProps {
  id?: string;
  isOpen: boolean;
  initialMode?: AuthMode;
  availableTenants?: TenantOption[];
  onClose: () => void;
}

export function renderAuthModal(props: AuthModalProps): string {
  const {
    id = "auth-modal",
    isOpen = false,
    initialMode = "signin",
    availableTenants = [],
  } = props;

  const studioPill = renderHighlighterPill({ text: "Studio", variant: "mint" });

  return `
    <div 
      id="${id}" 
      class="modal-overlay ${isOpen ? "open" : ""}" 
      role="dialog" 
      aria-modal="true" 
      aria-labelledby="auth-modal-title"
    >
      <div class="modal-card auth-modal-card" role="document">
        <!-- Close Button -->
        <button 
          type="button" 
          class="modal-close-btn" 
          id="auth-modal-close-btn"
          aria-label="Close authentication dialog"
          style="position: absolute; top: 20px; right: 20px; background: none; border: none; font-size: 22px; cursor: pointer; color: var(--ink-secondary); line-height: 1; padding: 4px;"
        >
          &times;
        </button>

        <!-- Header -->
        <div class="auth-header">
          <h2 id="auth-modal-title" class="auth-title">
            Step into your ${studioPill}
          </h2>
          <p class="auth-subtitle" id="auth-modal-subtitle">
            Private visual search, face clustering, and archive management.
          </p>
        </div>

        <!-- Mode Segment Control (Tabs) -->
        <div class="auth-segment-switch" role="tablist" aria-label="Authentication options">
          <button 
            type="button" 
            role="tab" 
            id="tab-btn-signin"
            class="auth-tab-btn ${initialMode === "signin" ? "active" : ""}"
            aria-selected="${initialMode === "signin"}"
            aria-controls="auth-panel-signin"
          >
            Sign In
          </button>
          <button 
            type="button" 
            role="tab" 
            id="tab-btn-signup"
            class="auth-tab-btn ${initialMode === "signup" ? "active" : ""}"
            aria-selected="${initialMode === "signup"}"
            aria-controls="auth-panel-signup"
          >
            Create Workspace
          </button>
        </div>

        <!-- Alert / Feedback Notification Banner -->
        <div id="auth-alert" class="auth-alert-box" style="display: none;" role="alert">
          <span id="auth-alert-icon">!</span>
          <span id="auth-alert-text"></span>
        </div>

        <!-- ============================================================== -->
        <!-- VIEW 1: SIGN IN FORM                                           -->
        <!-- ============================================================== -->
        <form 
          id="auth-form-signin" 
          class="auth-form-panel" 
          style="display: ${initialMode === "signin" ? "block" : "none"};"
          novalidate
        >
          <div class="form-group">
            <label for="signin-email" class="form-label">Email address</label>
            <input 
              type="email" 
              id="signin-email" 
              name="email"
              class="form-input" 
              placeholder="you@yourstudio.com" 
              autocomplete="email"
              required 
            />
          </div>

          <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
              <label for="signin-password" class="form-label" style="margin-bottom: 0;">Password</label>
              <button 
                type="button" 
                id="btn-forgot-password" 
                class="auth-footer-link" 
                style="font-size: 12px;"
              >
                Forgot password?
              </button>
            </div>
            <div class="input-wrapper">
              <input 
                type="password" 
                id="signin-password" 
                name="password"
                class="form-input" 
                placeholder="••••••••" 
                autocomplete="current-password"
                required 
              />
              <button 
                type="button" 
                class="input-toggle-btn" 
                id="toggle-signin-password"
                aria-label="Show password as plain text"
                title="Toggle password visibility"
              >
                Show
              </button>
            </div>
          </div>

          <button 
            type="submit" 
            id="signin-submit-btn" 
            class="btn-pill-black auth-submit-btn"
          >
            <span id="signin-btn-text">Sign In to Studio</span>
          </button>

          <p class="auth-footer-prompt">
            New to Velunara? 
            <button type="button" class="auth-footer-link" id="switch-to-signup-link">
              Create a free studio workspace
            </button>
          </p>
        </form>

        <!-- ============================================================== -->
        <!-- VIEW 2: SIGN UP / CREATE STUDIO FORM                           -->
        <!-- ============================================================== -->
        <form 
          id="auth-form-signup" 
          class="auth-form-panel" 
          style="display: ${initialMode === "signup" ? "block" : "none"};"
          novalidate
        >
          <div class="form-group">
            <label for="signup-org-name" class="form-label">Studio or Workspace Name</label>
            <input 
              type="text" 
              id="signup-org-name" 
              name="organization_name"
              class="form-input" 
              placeholder="e.g. Lumina Creative Archive" 
              required 
            />
            <p class="form-helper">This names your private gallery space and tenant container.</p>
          </div>

          <div class="form-group">
            <label for="signup-username" class="form-label">Admin Username</label>
            <input 
              type="text" 
              id="signup-username" 
              name="username"
              class="form-input" 
              placeholder="e.g. elena_director" 
              autocomplete="username"
              required 
            />
            <p class="form-helper">Letters, numbers, underscores, or hyphens (min 3 chars).</p>
          </div>

          <div class="form-group">
            <label for="signup-email" class="form-label">Email address</label>
            <input 
              type="email" 
              id="signup-email" 
              name="email"
              class="form-input" 
              placeholder="director@lumina.com" 
              autocomplete="email"
              required 
            />
          </div>

          <div class="form-group">
            <label for="signup-password" class="form-label">Password</label>
            <div class="input-wrapper">
              <input 
                type="password" 
                id="signup-password" 
                name="password"
                class="form-input" 
                placeholder="At least 8 characters" 
                autocomplete="new-password"
                required 
              />
              <button 
                type="button" 
                class="input-toggle-btn" 
                id="toggle-signup-password"
                aria-label="Show password as plain text"
                title="Toggle password visibility"
              >
                Show
              </button>
            </div>
            <p class="form-helper">Minimum 8 characters with a mix of characters.</p>
          </div>

          <!-- Pending Invite Checkbox (shown only if conflict occurs) -->
          <div id="pending-invite-container" style="display: none; margin-bottom: 16px; padding: 12px; background-color: var(--surface-muted); border-radius: 10px;">
            <label style="display: flex; align-items: flex-start; gap: 8px; font-size: 13px; color: var(--ink-primary); cursor: pointer;">
              <input type="checkbox" id="ignore-pending-invite-cb" style="margin-top: 2px;" />
              <span>Create independent studio despite pending invite to another workspace.</span>
            </label>
          </div>

          <button 
            type="submit" 
            id="signup-submit-btn" 
            class="btn-pill-black auth-submit-btn"
          >
            <span id="signup-btn-text">Create Workspace</span>
          </button>

          <p class="auth-footer-prompt">
            Already have a studio? 
            <button type="button" class="auth-footer-link" id="switch-to-signin-link">
              Sign in with your existing account
            </button>
          </p>
        </form>

        <!-- ============================================================== -->
        <!-- VIEW 3: MULTI-TENANT DISAMBIGUATION (Choose Workspace)          -->
        <!-- ============================================================== -->
        <div 
          id="auth-panel-disambiguate" 
          class="auth-form-panel" 
          style="display: ${initialMode === "disambiguate" ? "block" : "none"};"
        >
          <p style="font-size: 14px; color: var(--ink-secondary); margin-bottom: 16px; line-height: 1.5;">
            Your account belongs to multiple studio workspaces. Select which gallery you would like to enter:
          </p>

          <div 
            id="disambiguation-list" 
            style="display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px; max-height: 240px; overflow-y: auto;"
          >
            ${availableTenants.map(tenant => `
              <button
                type="button"
                class="workspace-card"
                data-disambiguate-tenant="${tenant.tenant_id}"
                style="
                  display: flex; 
                  align-items: center; 
                  justify-content: space-between; 
                  padding: 12px 16px; 
                  border: 1px solid var(--border-subtle); 
                  border-radius: 12px; 
                  background: var(--card); 
                  cursor: pointer; 
                  width: 100%;
                  text-align: left;
                  transition: all 0.15s ease;
                "
              >
                <div>
                  <div style="font-weight: 600; font-size: 14px; color: var(--ink-primary);">
                    ${tenant.organization_name}
                  </div>
                  <div style="font-size: 12px; color: var(--ink-secondary); margin-top: 2px;">
                    Role: <span style="text-transform: capitalize;">${tenant.role}</span>
                  </div>
                </div>
                <span style="font-size: 16px; color: var(--ink-secondary);">→</span>
              </button>
            `).join("")}
          </div>

          <button 
            type="button" 
            id="btn-back-to-login" 
            class="btn-secondary" 
            style="width: 100%;"
          >
            ← Back to Login
          </button>
        </div>

      </div>
    </div>
  `;
}

