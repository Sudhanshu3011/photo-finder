/**
 * WorkspaceSelector Component
 * Multi-Tenant Studio Organization Switcher
 * Follows Elementum Editorial design, WCAG 2.2 AA accessibility, and anti-slop rules.
 */

import { TenantOption } from "../../types/auth.types";
import { workspaceStore } from "../../stores/workspaceStore";
import { renderHighlighterPill } from "../../components/primitives/HighlighterPill";
import { renderButtonPill } from "../../components/primitives/ButtonPill";

export interface WorkspaceSelectorProps {
  id?: string;
  isOpen: boolean;
  onSelect: (tenantId: string) => void;
  onClose: () => void;
  onCreateNew?: () => void;
}

export function renderWorkspaceSelector(props: WorkspaceSelectorProps): string {
  const {
    id = "workspace-selector-modal",
    isOpen,
    onClose,
  } = props;

  const currentTenantId = workspaceStore.getCurrentTenantId();
  const availableTenants = workspaceStore.getAvailableTenants();
  const pendingInviteCount = workspaceStore.getPendingInviteCount();

  const titleWithPill = `Select your active ${renderHighlighterPill({ text: "workspace", variant: "mint" })}`;

  const contentHtml = `
    <p style="font-size: 14px; color: var(--ink-secondary); margin-bottom: 20px; line-height: 1.5;">
      Choose the organization or studio gallery you wish to work in. Your permissions and albums will automatically adapt.
    </p>

    <!-- Workspace List -->
    <div 
      class="workspace-list" 
      role="listbox" 
      aria-label="Available studio workspaces"
      style="display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px;"
    >
      ${availableTenants.map(tenant => {
        const isSelected = tenant.tenant_id === currentTenantId;
        const initials = tenant.initials || tenant.organization_name.substring(0, 2).toUpperCase();
        const themeColor = tenant.theme_color || "var(--pill-mint-bg)";
        const rolePillVariant = tenant.role === "Studio Owner" || tenant.role === "owner" ? "mint" : "butter";

        return `
          <div 
            class="workspace-card"
            role="option"
            aria-selected="${isSelected}"
            tabindex="0"
            data-tenant-id="${tenant.tenant_id}"
            style="
              display: flex;
              align-items: center;
              justify-content: space-between;
              padding: 14px 18px;
              min-height: 64px;
              border: 1px solid ${isSelected ? "var(--ink-primary)" : "var(--border-subtle)"};
              border-radius: var(--radius-lg);
              background-color: ${isSelected ? "rgba(217, 239, 230, 0.25)" : "var(--card)"};
              cursor: pointer;
              transition: border-color 0.15s ease, background-color 0.15s ease;
            "
          >
            <div style="display: flex; align-items: center; gap: 14px;">
              <div 
                class="avatar-circle"
                style="
                  width: 44px;
                  height: 44px;
                  background-color: ${themeColor};
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  font-weight: 700;
                  font-size: 15px;
                  color: var(--ink-primary);
                  box-shadow: none;
                "
              >
                ${initials}
              </div>

              <div>
                <div style="font-family: var(--font-display); font-weight: 700; font-size: 16px; color: var(--ink-primary);">
                  ${tenant.organization_name}
                </div>
                <div style="font-size: 12px; color: var(--ink-muted); margin-top: 2px;">
                  ${tenant.photo_count ? `${tenant.photo_count.toLocaleString()} photos organized` : "Active workspace"}
                </div>
              </div>
            </div>

            <div style="display: flex; align-items: center; gap: 12px;">
              <span class="hl-pill ${rolePillVariant}" style="font-size: 11px; padding: 2px 10px;">
                ${tenant.role}
              </span>
              <span class="row-arrow" style="font-size: 18px; color: var(--ink-primary);" aria-hidden="true">
                ${isSelected ? "[Selected]" : "&rarr;"}
              </span>
            </div>
          </div>
        `;
      }).join("")}
    </div>

    <!-- Pending Invitation Banner -->
    ${pendingInviteCount > 0 ? `
      <div 
        style="
          background-color: var(--pill-butter-bg);
          border: 1px solid #FCD34D;
          border-radius: var(--radius-md);
          padding: 12px 16px;
          margin-bottom: 24px;
          font-size: 13px;
          color: var(--pill-butter-fg);
          display: flex;
          align-items: center;
          justify-content: space-between;
        "
      >
        <div>
          <strong>Pending Invitation:</strong> Apex Media Agency invited you as Contributor.
        </div>
        <a href="#accept-invite" style="font-weight: 700; color: #78350F; text-decoration: underline; margin-left: 8px;">
          Review &rarr;
        </a>
      </div>
    ` : ""}

    <!-- Action Button -->
    <div style="display: flex; justify-content: flex-end;">
      ${renderButtonPill({
        label: "+ Register New Organization",
        variant: "primary",
        className: "w-full justify-center",
        ariaLabel: "Create a new organization workspace",
      })}
    </div>
  `;

  return `
    <div 
      id="${id}"
      class="modal-overlay ${isOpen ? "open" : ""}"
      role="dialog"
      aria-modal="true"
      aria-label="Workspace Selection"
    >
      <div 
        class="modal-card" 
        style="max-width: 520px;"
        tabindex="-1"
      >
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px;">
          <h2 style="font-family: var(--font-display); font-size: 22px; font-weight: 700; margin: 0;">
            ${titleWithPill}
          </h2>
          <button 
            type="button"
            class="btn-secondary" 
            style="min-width: 44px; min-height: 44px; border: none; font-size: 20px; line-height: 1; padding: 0 12px;" 
            data-close-workspace-modal
            aria-label="Close dialog"
          >
            &times;
          </button>
        </div>

        <div class="modal-body">
          ${contentHtml}
        </div>
      </div>
    </div>
  `;
}

