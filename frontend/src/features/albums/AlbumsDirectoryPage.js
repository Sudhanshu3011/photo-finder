/**
 * AlbumsDirectoryPage Feature Component (ESM)
 * Displays the organization's photo collections with cover photography,
 * photo and people counts, privacy badges, and access management triggers.
 */

export function renderAlbumsDirectoryPage(props) {
  return `
    <div style="max-width: 1200px; margin: 0 auto; padding-bottom: 56px;">
      <!-- Header Banner with Create Collection Trigger -->
      <div style="margin-bottom: 36px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px;">
        <div>
          <span class="hl-pill mint" style="font-size: 12px; margin-bottom: 12px; display: inline-block;">Archival Architecture</span>
          <h1 style="font-size: clamp(28px, 4vw, 42px); line-height: 1.15; margin-bottom: 8px;">
            Your <span class="hl-pill mint">Collections</span>
          </h1>
          <p style="font-size: 15px; color: var(--ink-secondary); max-width: 600px;">
            Organize event archives, assign plain-English permissions to team members, and isolate sensitive photo assets.
          </p>
        </div>

        <div>
          <button 
            type="button" 
            class="btn-pill-black" 
            id="open-create-collection-modal-btn"
            style="padding: 12px 24px; font-size: 14px;"
          >
            + Create New Collection
          </button>
        </div>
      </div>

      <!-- Feedback Toast Banner -->
      ${props.toastNotice ? `
        <div style="background: #F0FDF4; border: 1px solid #DCFCE7; border-radius: 12px; padding: 12px 18px; margin-bottom: 24px; display: flex; align-items: center; justify-content: space-between; font-size: 14px; color: #166534;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span>[OK]</span>
            <span>${props.toastNotice}</span>
          </div>
          <button type="button" id="dismiss-album-toast-btn" style="background: none; border: none; font-size: 16px; cursor: pointer; color: #166534;">&times;</button>
        </div>
      ` : ""}

      <!-- Loading State -->
      ${props.isLoading ? `
        <div style="text-align: center; padding: 64px 0; color: var(--ink-secondary);">
          <div style="font-size: 14px; font-weight: 600; color: #64748B; margin-bottom: 8px;">No Collections</div>
          <p style="font-size: 15px;">Loading workspace collections...</p>
        </div>
      ` : ""}

      <!-- Empty State -->
      ${!props.isLoading && props.albums.length === 0 ? `
        <div style="text-align: center; padding: 72px 24px; background: var(--card); border: 1px dashed var(--border-subtle); border-radius: var(--radius-lg); margin-top: 16px;">
          <div style="font-size: 14px; font-weight: 600; color: #64748B; margin-bottom: 8px;">No Collections</div>
          <h3 style="font-size: 20px; font-weight: 700; margin-bottom: 8px;">No collections yet</h3>
          <p style="font-size: 14px; color: var(--ink-secondary); max-width: 440px; margin: 0 auto 24px auto;">
            Create your first collection to start storing, grouping, and securely sharing your organization's photo archives.
          </p>
          <button type="button" class="btn-pill-black" id="empty-create-collection-btn">
            + Create Your First Collection
          </button>
        </div>
      ` : ""}

      <!-- Collections Grid -->
      <div class="results-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 24px;">
        ${props.albums.map((album) => `
          <div 
            class="photo-card" 
            style="
              background: var(--card, #FFFFFF); 
              border: 1px solid var(--border-subtle); 
              border-radius: var(--radius-lg, 16px); 
              overflow: hidden; 
              display: flex; 
              flex-direction: column;
              box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02);
              transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.2s ease;
            "
          >
            <!-- Cover Photography -->
            <div style="width: 100%; height: 210px; background: var(--surface-muted); position: relative; overflow: hidden;">
              <img 
                src="${album.coverUrl || "https://images.unsplash.com/photo-1511578314322-379afb476865?auto=format&fit=crop&w=800&q=80"}" 
                alt="${album.title}" 
                style="width: 100%; height: 100%; object-fit: cover; display: block;" 
              />
              
              <!-- Privacy Status Badge -->
              <div style="position: absolute; top: 12px; right: 12px;">
                <span 
                  class="hl-pill ${album.isPrivate ? "butter" : "mint"}" 
                  style="font-size: 11px; font-weight: 600; padding: 4px 10px; backdrop-filter: blur(8px);"
                >
                  ${album.isPrivate ? "Restricted" : "Workspace-Wide"}
                </span>
              </div>

              <!-- Effective Capability Pill -->
              <div style="position: absolute; bottom: 12px; left: 12px;">
                <span 
                  style="
                    background: rgba(17, 24, 28, 0.75); 
                    color: #FFFFFF; 
                    font-size: 11px; 
                    font-weight: 600; 
                    padding: 3px 8px; 
                    border-radius: 6px; 
                    backdrop-filter: blur(4px);
                  "
                >
                  ${album.canManage ? "Full Access" : album.canUpload ? "Can Add" : "View Only"}
                </span>
              </div>
            </div>

            <!-- Card Body -->
            <div style="padding: 20px 22px; flex: 1; display: flex; flex-direction: column;">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <h3 style="font-size: 18px; font-weight: 700; color: var(--ink); line-height: 1.3;">
                  ${album.title}
                </h3>
              </div>

              <p style="font-size: 13px; color: var(--ink-secondary); line-height: 1.5; margin-bottom: 16px; flex: 1;">
                ${album.description || "Archival collection for organization events and team photos."}
              </p>

              <!-- Metadata Metrics -->
              <div style="display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--ink-muted); padding-bottom: 16px; border-bottom: 1px solid var(--surface-muted); margin-bottom: 16px;">
                <span>${album.photoCount || 0} photos</span>
                <span>${album.peopleCount || 0} people recognized</span>
              </div>

              <!-- Card Actions -->
              <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                <div style="display: flex; align-items: center; gap: 6px;">
                  <button 
                    type="button" 
                    class="btn-secondary search-in-album-btn" 
                    data-album-title="${album.title}"
                    style="font-size: 12px; padding: 6px 10px;"
                  >
                    Search
                  </button>

                  ${album.canUpload !== false ? `
                    <button 
                      type="button" 
                      class="btn-secondary upload-to-album-btn" 
                      data-album-title="${album.title}"
                      style="font-size: 12px; padding: 6px 10px; background: rgba(17, 24, 28, 0.05); font-weight: 600;"
                    >
                      Upload &rarr;
                    </button>
                  ` : ""}
                </div>

                <div style="display: flex; align-items: center; gap: 6px;">
                  ${album.canManage ? `
                    <button 
                      type="button" 
                      class="btn-secondary open-album-permissions-btn" 
                      data-album-id="${album.id}"
                      data-album-title="${album.title}"
                      style="font-size: 12px; padding: 6px 10px;"
                    >
                      Permissions
                    </button>
                  ` : `
                    <span style="font-size: 11px; color: var(--ink-muted); padding: 4px 6px;">
                      View-only
                    </span>
                  `}

                  ${album.canDelete ? `
                    <button 
                      type="button" 
                      class="delete-album-btn" 
                      data-album-id="${album.id}"
                      data-album-title="${album.title}"
                      aria-label="Delete collection"
                      style="background: none; border: none; font-size: 14px; cursor: pointer; color: var(--ink-muted); padding: 4px 6px;"
                      title="Delete collection"
                    >Delete</button>
                  ` : ""}
                </div>
              </div>
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

