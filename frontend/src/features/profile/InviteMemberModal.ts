/**
 * InviteMemberModal Component
 * Interactive modal for Admin to invite collaborators with pre-granted folder permissions.
 * Adheres to Elementum tokens, WCAG 44px touch targets, and anti-slop guidelines.
 */

import { FolderDto } from "../../services/api/folderApi";

export interface InviteMemberModalProps {
  isOpen: boolean;
  folders: FolderDto[];
  isSubmitting?: boolean;
  error?: string | null;
  generatedLink?: string | null;
  onClose: () => void;
}

export function renderInviteMemberModal(props: InviteMemberModalProps): string {
  const {
    isOpen,
    folders,
    isSubmitting = false,
    error = null,
    generatedLink = null,
  } = props;

  return `
    <div 
      class="modal-overlay ${isOpen ? "open" : ""}" 
      id="invite-member-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="invite-modal-title"
      style="display: ${isOpen ? "flex" : "none"}; align-items: center; justify-content: center; position: fixed; inset: 0; background: rgba(17, 24, 28, 0.45); backdrop-filter: blur(6px); z-index: 1000;"
    >
      <div 
        class="modal-card" 
        style="
          background: var(--card, #FFFFFF); 
          border: 1px solid var(--border-subtle); 
          border-radius: var(--radius-lg, 16px); 
          padding: 32px; 
          width: 100%; 
          max-width: 540px; 
          max-height: 90vh;
          overflow-y: auto;
          box-shadow: 0 12px 40px rgba(0, 0, 0, 0.12);
        "
      >
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
          <div>
            <span class="hl-pill mint" style="font-size: 11px; margin-bottom: 6px; display: inline-block;">Team Onboarding</span>
            <h3 id="invite-modal-title" style="font-size: 22px; font-weight: 700; color: var(--ink-primary); margin: 0;">Invite Collaborator</h3>
          </div>
          <button 
            type="button" 
            class="btn-secondary" 
            style="border: none; padding: 4px 10px; font-size: 18px; cursor: pointer; color: var(--ink-muted);" 
            id="close-invite-modal-btn"
            aria-label="Close dialog"
          >&times;</button>
        </div>

        ${error ? `
          <div style="background: #FEF2F2; border: 1px solid #FEE2E2; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; color: #DC2626;">
            ${error}
          </div>
        ` : ""}

        ${generatedLink ? `
          <div style="background: rgba(217, 239, 230, 0.35); border: 1px solid #A7F3D0; border-radius: 12px; padding: 18px; margin-bottom: 20px;">
            <div style="font-weight: 700; font-size: 14px; color: #065F46; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
              <span>[OK]</span> Invitation Link Generated!
            </div>
            <p style="font-size: 13px; color: var(--ink-secondary); margin: 0 0 12px 0;">
              Share this secure registration link with your collaborator. It grants immediate access with your selected folder permissions upon signup.
            </p>
            <div style="display: flex; gap: 8px; align-items: center;">
              <input 
                type="text" 
                readonly 
                value="${generatedLink}" 
                id="generated-invite-link-input"
                style="width: 100%; padding: 9px 12px; border: 1px solid var(--border-subtle); border-radius: 8px; font-size: 12px; background: #FFFFFF; font-family: monospace;" 
              />
              <button 
                type="button" 
                class="btn-pill-black" 
                id="copy-invite-link-btn"
                style="min-height: 38px; padding: 0 14px; font-size: 12px; white-space: nowrap;"
              >
                Copy Link
              </button>
            </div>
            <div id="copy-feedback-msg" style="font-size: 12px; color: #10B981; margin-top: 6px; display: none;">
              Link copied to clipboard!
            </div>
          </div>
        ` : ""}

        <form id="invite-member-form" onsubmit="return false;">
          <!-- Email Input -->
          <div style="margin-bottom: 18px;">
            <label for="invite-email-input" style="display: block; font-size: 13px; font-weight: 600; color: var(--ink-primary); margin-bottom: 6px;">
              Collaborator Email <span style="color: #DC2626;">*</span>
            </label>
            <input 
              type="email" 
              id="invite-email-input" 
              placeholder="e.g. photographer@agency.com" 
              required
              style="width: 100%; padding: 11px 14px; border: 1px solid var(--border-subtle); border-radius: 8px; font-size: 14px; background: var(--ground); color: var(--ink-primary); outline: none;"
            />
          </div>

          <!-- Role Select -->
          <div style="margin-bottom: 18px;">
            <label for="invite-role-select" style="display: block; font-size: 13px; font-weight: 600; color: var(--ink-primary); margin-bottom: 6px;">
              Organization Role
            </label>
            <select 
              id="invite-role-select"
              style="width: 100%; padding: 11px 14px; border: 1px solid var(--border-subtle); border-radius: 8px; font-size: 14px; background: var(--ground); color: var(--ink-primary); outline: none;"
            >
              <option value="contributor" selected>Contributor (Can upload photos &amp; manage permitted collections)</option>
              <option value="viewer">Viewer (Can search &amp; view permitted collections)</option>
              <option value="admin">Administrator (Full workspace rights, invite teammates, delete collections)</option>
            </select>
          </div>

          <!-- Pre-Grant Folder Permissions Checklist -->
          <div style="margin-bottom: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="display: block; font-size: 13px; font-weight: 600; color: var(--ink-primary);">
                Pre-Grant Collection Access
              </label>
              <span style="font-size: 11px; color: var(--ink-muted);">Auto-assigned upon signup</span>
            </div>

            <div style="max-height: 160px; overflow-y: auto; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 10px 14px; background: var(--surface-muted, #FAFAFA);">
              ${folders.length > 0 ? folders.map(f => `
                <label style="display: flex; align-items: center; gap: 10px; padding: 6px 0; cursor: pointer; font-size: 13px; color: var(--ink-primary);">
                  <input type="checkbox" name="invite-pregrant-folder" value="${f.folder_id}" style="accent-color: var(--ink-primary);" />
                  <span style="font-weight: 600;">${f.folder_name}</span>
                  <span style="font-size: 11px; color: var(--ink-muted); margin-left: auto;">${(f.photo_count || 0)} photos</span>
                </label>
              `).join("") : `
                <div style="font-size: 12px; color: var(--ink-muted); padding: 8px 0;">No collections created yet.</div>
              `}
            </div>
          </div>

          <!-- Initial Access Level for Pre-Granted Folders -->
          <div style="margin-bottom: 24px;">
            <label for="invite-access-level-select" style="display: block; font-size: 13px; font-weight: 600; color: var(--ink-primary); margin-bottom: 6px;">
              Access Level for Selected Collections
            </label>
            <select 
              id="invite-access-level-select"
              style="width: 100%; padding: 11px 14px; border: 1px solid var(--border-subtle); border-radius: 8px; font-size: 14px; background: var(--ground); color: var(--ink-primary); outline: none;"
            >
              <option value="uploader" selected>Uploader (Can upload new photos &amp; search)</option>
              <option value="viewer">Viewer (Read-only search &amp; face retrieval)</option>
              <option value="manager">Manager (Can manage collection &amp; adjust sharing)</option>
            </select>
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 12px;">
            <button 
              type="button" 
              class="btn-secondary" 
              id="cancel-invite-modal-btn"
              style="min-height: 40px; padding: 0 16px; font-size: 13px;"
            >
              Cancel
            </button>
            <button 
              type="submit" 
              class="btn-pill-black" 
              id="submit-invite-btn"
              style="min-height: 40px; padding: 0 20px; font-size: 13px;"
              ${isSubmitting ? "disabled" : ""}
            >
              ${isSubmitting ? "Sending Invitation..." : "Send Invitation"}
            </button>
          </div>
        </form>
      </div>
    </div>
  `;
}

