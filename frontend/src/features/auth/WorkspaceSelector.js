import { workspaceStore } from "../../stores/workspaceStore.js";
import { renderHighlighterPill } from "../../components/primitives/HighlighterPill.js";
import { renderButtonPill } from "../../components/primitives/ButtonPill.js";

export function renderWorkspaceSelector(props = {}) {
  const {
    id = "workspace-selector-modal",
    isOpen = false,
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
            <!-- Left: Avatar badge & details -->
            <div style="display: flex; align-items: center; gap: 14px;">
              <div 
                style="
                  width: 40px;
                  height: 40px;
                  border-radius: 50%;
                  background-color: ${themeColor};
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  font-weight: 700;
                  font-size: 14px;
                  color: var(--ink-primary);
                "
                aria-hidden="true"
              >
                ${initials}
              </div>

              <div>
                <div style="font-weight: 700; font-size: 15px; color: var(--ink-primary); margin-bottom: 2px;">
                  ${tenant.organization_name}
                </div>
                <div style="font-size: 13px; color: var(--ink-secondary);">
                  ${tenant.photo_count !== undefined ? `${tenant.photo_count} photos · ` : ""}${tenant.role}
                </div>
              </div>
            </div>

            <!-- Right: Role Pill & selection check -->
            <div style="display: flex; align-items: center; gap: 10px;">
              ${renderHighlighterPill({ text: tenant.role, variant: rolePillVariant })}
              ${isSelected ? `
                <span 
                  style="
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 24px;
                    height: 24px;
                    border-radius: 50%;
                    background-color: var(--ink-primary);
                    color: #FFFFFF;
                    font-size: 12px;
                  "
                  aria-label="Active selection"
                >
                  [OK]
                </span>
              ` : `
                <span style="font-size: 18px; color: var(--ink-muted); padding: 0 4px;" aria-hidden="true">→</span>
              `}
            </div>
          </div>
        `;
      }).join("")}
    </div>

    <!-- Pending Invitations Banner (if any) -->
    ${pendingInviteCount > 0 ? `
      <div 
        style="
          padding: 12px 16px;
          border-radius: var(--radius-md);
          background-color: var(--pill-butter-bg);
          color: var(--pill-butter-fg);
          font-size: 13px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 20px;
        "
      >
        <span>You have <strong>${pendingInviteCount} pending workspace invitation</strong></span>
        <button 
          class="auth-footer-link"
          id="btn-view-invites"
          style="font-size: 12px; font-weight: 700; color: var(--pill-butter-fg);"
        >
          Review →
        </button>
      </div>
    ` : ""}

    <!-- Footer Actions -->
    <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 16px; border-top: 1px solid var(--border-subtle);">
      ${renderButtonPill({
        label: "+ Create New Studio",
        variant: "secondary",
        id: "btn-create-new-workspace",
        ariaLabel: "Create another workspace organization",
      })}

      ${renderButtonPill({
        label: "Done",
        variant: "primary",
        id: "btn-close-workspace-selector",
        ariaLabel: "Close workspace switcher",
      })}
    </div>
  `;

  return `
    <div 
      id="${id}" 
      class="modal-overlay ${isOpen ? "open" : ""}" 
      role="dialog" 
      aria-modal="true" 
      aria-labelledby="workspace-modal-title"
    >
      <div class="modal-card" style="max-width: 540px;" role="document">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
          <h2 id="workspace-modal-title" style="font-size: 22px; font-weight: 800; font-family: var(--font-display);">
            ${titleWithPill}
          </h2>
          <button 
            type="button" 
            class="modal-close-btn" 
            id="workspace-modal-close-btn"
            aria-label="Close dialog"
            style="background: none; border: none; font-size: 22px; cursor: pointer; color: var(--ink-secondary); line-height: 1; padding: 4px;"
          >
            &times;
          </button>
        </div>
        ${contentHtml}
      </div>
    </div>
  `;
}

