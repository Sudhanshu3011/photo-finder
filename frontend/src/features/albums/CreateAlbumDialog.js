/**
 * CreateAlbumDialog Component (ESM)
 * Modal dialog for creating a new collection with name, description, and privacy toggle.
 */

export function renderCreateAlbumDialog(props) {
  return `
    <div 
      class="modal-overlay ${props.isOpen ? "open" : ""}" 
      id="create-album-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-album-title"
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
          max-width: 520px; 
          box-shadow: 0 12px 40px rgba(0, 0, 0, 0.12);
        "
      >
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
          <div>
            <span class="hl-pill mint" style="font-size: 11px; margin-bottom: 6px; display: inline-block;">New Workspace Collection</span>
            <h3 id="create-album-title" style="font-size: 22px; font-weight: 700; color: var(--ink);">Create Collection</h3>
          </div>
          <button 
            type="button" 
            class="btn-secondary" 
            style="border: none; padding: 4px 10px; font-size: 18px; cursor: pointer; color: var(--ink-muted);" 
            id="close-create-album-modal-btn"
            aria-label="Close dialog"
          >&times;</button>
        </div>

        ${props.error ? `
          <div style="background: #FEF2F2; border: 1px solid #FEE2E2; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; color: #DC2626;">
            ${props.error}
          </div>
        ` : ""}

        <form id="create-album-form" onsubmit="return false;">
          <div style="margin-bottom: 18px;">
            <label for="new-album-name-input" style="display: block; font-size: 13px; font-weight: 600; color: var(--ink); margin-bottom: 6px;">
              Collection Name <span style="color: #DC2626;">*</span>
            </label>
            <input 
              type="text" 
              id="new-album-name-input" 
              placeholder="e.g., Executive Leadership Summit 2026" 
              required
              style="width: 100%; padding: 11px 14px; border: 1px solid var(--border-subtle); border-radius: 8px; font-size: 14px; background: var(--ground); color: var(--ink); outline: none;"
            />
          </div>

          <div style="margin-bottom: 20px;">
            <label for="new-album-desc-input" style="display: block; font-size: 13px; font-weight: 600; color: var(--ink); margin-bottom: 6px;">
              Description (Optional)
            </label>
            <textarea 
              id="new-album-desc-input" 
              rows="3" 
              placeholder="Brief context regarding events, teams or photography scope..."
              style="width: 100%; padding: 11px 14px; border: 1px solid var(--border-subtle); border-radius: 8px; font-size: 13px; background: var(--ground); color: var(--ink); outline: none; resize: vertical;"
            ></textarea>
          </div>

          <div style="margin-bottom: 24px;">
            <label style="display: block; font-size: 13px; font-weight: 600; color: var(--ink); margin-bottom: 8px;">
              Visibility &amp; Access Mode
            </label>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
              <label 
                style="
                  display: flex; 
                  flex-direction: column; 
                  gap: 4px; 
                  padding: 12px 14px; 
                  border: 1px solid var(--border-subtle); 
                  border-radius: 10px; 
                  background: var(--surface-muted); 
                  cursor: pointer;
                "
              >
                <div style="display: flex; align-items: center; gap: 8px;">
                  <input type="radio" name="new-album-visibility" value="restricted" checked style="accent-color: var(--ink);" />
                  <span style="font-weight: 600; font-size: 13px; color: var(--ink);">Restricted (Private)</span>
                </div>
                <span style="font-size: 11px; color: var(--ink-muted); margin-left: 24px;">
                  Only invited team members can view or add photos.
                </span>
              </label>

              <label 
                style="
                  display: flex; 
                  flex-direction: column; 
                  gap: 4px; 
                  padding: 12px 14px; 
                  border: 1px solid var(--border-subtle); 
                  border-radius: 10px; 
                  background: var(--surface-muted); 
                  cursor: pointer;
                "
              >
                <div style="display: flex; align-items: center; gap: 8px;">
                  <input type="radio" name="new-album-visibility" value="tenant_wide" style="accent-color: var(--ink);" />
                  <span style="font-weight: 600; font-size: 13px; color: var(--ink);">Workspace-Wide</span>
                </div>
                <span style="font-size: 11px; color: var(--ink-muted); margin-left: 24px;">
                  Everyone in this organization can search and view photos.
                </span>
              </label>
            </div>
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 12px;">
            <button type="button" class="btn-secondary" id="cancel-create-album-btn">
              Cancel
            </button>
            <button 
              type="submit" 
              class="btn-pill-black" 
              id="submit-create-album-btn"
              ${props.isSubmitting ? "disabled" : ""}
            >
              ${props.isSubmitting ? "Creating..." : "Create Collection"}
            </button>
          </div>
        </form>
      </div>
    </div>
  `;
}
