/**
 * GranularPermissions Component (ESM)
 * Plain-language member access matrix for albums.
 */

export function renderGranularPermissionsModal(props) {
  return `
    <div 
      class="modal-overlay ${props.isOpen ? "open" : ""}" 
      id="permissions-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="permissions-modal-title"
      style="display: ${props.isOpen ? "flex" : "none"}; align-items: center; justify-content: center; position: fixed; inset: 0; background: rgba(17, 24, 28, 0.45); backdrop-filter: blur(6px); z-index: 1000;"
    >
      <div 
        class="modal-card" 
        style="
          background: var(--card, #FFFFFF); 
          border: 1px solid var(--border-subtle); 
          border-radius: var(--radius-lg, 16px); 
          padding: 32px; 
          width: 100%; 
          max-width: 680px; 
          box-shadow: 0 12px 40px rgba(0, 0, 0, 0.12);
          max-height: 90vh;
          overflow-y: auto;
        "
      >
        <!-- Modal Header -->
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
          <div>
            <span class="hl-pill mint" style="font-size: 11px; margin-bottom: 6px; display: inline-block;">Collection Permissions</span>
            <h3 id="permissions-modal-title" style="font-size: 22px; font-weight: 700; color: var(--ink);">
              ${props.albumTitle || "Album Sharing"}
            </h3>
          </div>
          <button 
            type="button" 
            class="btn-secondary" 
            style="border: none; padding: 4px 10px; font-size: 18px; cursor: pointer; color: var(--ink-muted);" 
            id="close-permissions-modal-btn"
            aria-label="Close dialog"
          >&times;</button>
        </div>

        <p style="font-size: 14px; color: var(--ink-secondary); margin-bottom: 20px; line-height: 1.5;">
          ${props.canEdit 
            ? "Set plain-language capabilities for team members on this collection. Changes take effect across the workspace immediately."
            : "You have view-only access to this collection's access list. Only collection managers and organization admins can modify sharing."}
        </p>

        ${props.error ? `
          <div style="background: #FEF2F2; border: 1px solid #FEE2E2; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; color: #DC2626;">
            ${props.error}
          </div>
        ` : ""}

        <!-- Permissions Matrix Table -->
        <div style="border: 1px solid var(--border-subtle); border-radius: 12px; overflow: hidden; margin-bottom: 24px;">
          <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
              <tr style="background: var(--surface-muted); border-bottom: 1px solid var(--border-subtle); text-align: left; color: var(--ink-muted);">
                <th style="padding: 12px 16px; font-weight: 600;">Team Member</th>
                <th style="padding: 12px 10px; text-align: center; font-weight: 600;" title="Can view and search through photos in this collection">
                  Can View
                </th>
                <th style="padding: 12px 10px; text-align: center; font-weight: 600;" title="Can add and upload new photos to this collection">
                  Can Add
                </th>
                <th style="padding: 12px 10px; text-align: center; font-weight: 600;" title="Can manage sharing, edit collection metadata, and delete photos">
                  Full Management
                </th>
              </tr>
            </thead>
            <tbody>
              ${props.members.map((m) => `
                <tr 
                  class="member-permission-row" 
                  data-user-id="${m.userId}"
                  style="border-bottom: 1px solid var(--surface-muted); transition: background 0.15s ease;"
                >
                  <!-- Member Info -->
                  <td style="padding: 12px 16px;">
                    <div style="display: flex; align-items: center; gap: 12px;">
                      <div 
                        style="
                          width: 36px; 
                          height: 36px; 
                          border-radius: 50%; 
                          background: var(--mint-field, #D9EFE6); 
                          display: flex; 
                          align-items: center; 
                          justify-content: center; 
                          font-weight: 700; 
                          font-size: 13px;
                          color: #064E3B;
                          flex-shrink: 0;
                          overflow: hidden;
                        "
                      >
                        ${m.userAvatarUrl 
                          ? `<img src="${m.userAvatarUrl}" alt="${m.userName}" style="width: 100%; height: 100%; object-fit: cover;" />`
                          : m.userName.substring(0, 2).toUpperCase()}
                      </div>
                      <div style="min-width: 0;">
                        <div style="font-weight: 600; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                          ${m.userName}
                          ${m.isOwner ? `<span class="hl-pill mint" style="font-size: 10px; margin-left: 6px; padding: 2px 6px;">Creator</span>` : ""}
                        </div>
                        <div style="font-size: 11px; color: var(--ink-muted);">
                          ${m.userEmail || m.tenantRole}
                        </div>
                      </div>
                    </div>
                  </td>

                  <!-- Checkbox 1: Can View -->
                  <td style="text-align: center; padding: 12px 10px;">
                    <input 
                      type="checkbox" 
                      class="perm-checkbox perm-view" 
                      data-user-id="${m.userId}" 
                      ${m.canView ? "checked" : ""} 
                      ${!props.canEdit || m.isOwner ? "disabled" : ""}
                      style="accent-color: var(--ink); width: 16px; height: 16px; cursor: ${props.canEdit && !m.isOwner ? "pointer" : "not-allowed"};"
                    />
                  </td>

                  <!-- Checkbox 2: Can Add Photos -->
                  <td style="text-align: center; padding: 12px 10px;">
                    <input 
                      type="checkbox" 
                      class="perm-checkbox perm-add" 
                      data-user-id="${m.userId}" 
                      ${m.canAddPhotos ? "checked" : ""} 
                      ${!props.canEdit || m.isOwner ? "disabled" : ""}
                      style="accent-color: var(--ink); width: 16px; height: 16px; cursor: ${props.canEdit && !m.isOwner ? "pointer" : "not-allowed"};"
                    />
                  </td>

                  <!-- Checkbox 3: Full Management -->
                  <td style="text-align: center; padding: 12px 10px;">
                    <input 
                      type="checkbox" 
                      class="perm-checkbox perm-manage" 
                      data-user-id="${m.userId}" 
                      ${m.canManage ? "checked" : ""} 
                      ${!props.canEdit || m.isOwner ? "disabled" : ""}
                      style="accent-color: var(--ink); width: 16px; height: 16px; cursor: ${props.canEdit && !m.isOwner ? "pointer" : "not-allowed"};"
                    />
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>

        <!-- Action Footer -->
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="font-size: 12px; color: var(--ink-muted);">
            ${props.canEdit 
              ? "Changes apply to all future uploads into this collection" 
              : "Read-only view for your organization role"}
          </div>

          <div style="display: flex; gap: 12px;">
            <button type="button" class="btn-secondary" id="cancel-permissions-modal-btn">
              ${props.canEdit ? "Cancel" : "Close"}
            </button>
            ${props.canEdit ? `
              <button 
                type="button" 
                class="btn-pill-black" 
                id="save-permissions-modal-btn"
                ${props.isSaving ? "disabled" : ""}
              >
                ${props.isSaving ? "Saving..." : "Save Changes"}
              </button>
            ` : ""}
          </div>
        </div>
      </div>
    </div>
  `;
}
