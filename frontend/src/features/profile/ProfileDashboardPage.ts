/**
 * ProfileDashboardPage Feature Component
 * Authenticated User Hub & Role-Differentiated Workspace Dashboard
 * 
 * Implements strict role-based access presentation:
 * - Admin/Owner: Full workspace collection inventory, creation, deletion, invitations, member management.
 * - Manager: Managed collections, creation, "Who else can edit/view" transparent ACL inspection, granular sharing.
 * - Regular User: Permitted archives only, view/upload badges, zero clutter, distraction-free search shortcuts.
 */

import { UserProfile, TenantOption } from "../../types/auth.types";
import { FolderDto, TenantMemberDto } from "../../services/api/folderApi";
import { renderHighlighterPill } from "../../components/primitives/HighlighterPill";

export interface ProfileDashboardProps {
  user: UserProfile | null;
  currentOrg: string;
  currentTenantId: string;
  availableTenants: TenantOption[];
  folders: FolderDto[];
  members: TenantMemberDto[];
  isLoadingFolders?: boolean;
}

export function renderProfileDashboard(props: ProfileDashboardProps): string {
  const {
    user,
    currentOrg,
    currentTenantId,
    availableTenants,
    folders,
    members,
    isLoadingFolders = false,
  } = props;

  const displayName = user?.username || "Authenticated Member";
  const displayEmail = user?.email || "member@velunara.com";
  const rawRole = (user?.role || "viewer").toLowerCase();
  
  const isAdmin = rawRole === "owner" || rawRole === "admin";
  const isManager = !isAdmin && (rawRole === "manager" || rawRole === "editor");
  const isRegularUser = !isAdmin && !isManager;

  const roleTitle = isAdmin 
    ? "Workspace Administrator" 
    : isManager 
      ? "Collection Manager" 
      : "Archive Contributor & Viewer";

  const rolePillVariant: "mint" | "butter" | "rose" = isAdmin 
    ? "mint" 
    : isManager 
      ? "butter" 
      : "rose";

  // Filter folders based on role persona
  const displayedFolders = isAdmin
    ? folders
    : isManager
      ? folders.filter(f => f.can_manage || f.effective_access === "manager" || f.effective_access === "editor")
      : folders;

  const avatarUrl = user?.avatarUrl || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=200&q=80";

  return `
    <div class="home-container" style="max-width: 1140px; margin: 40px auto; padding: 0 24px;">
      <!-- Page Header -->
      <div style="margin-bottom: 32px;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <span class="hl-pill ${rolePillVariant}" style="font-size: 11px;">${roleTitle}</span>
          <span style="font-size: 13px; color: var(--ink-secondary);">Identity &amp; Workspace Authorization</span>
        </div>
        <h1 style="font-size: 32px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 8px 0;">Workspace Dashboard</h1>
        <p style="font-size: 15px; color: var(--ink-secondary); margin: 0; max-width: 720px; line-height: 1.5;">
          ${isAdmin 
            ? "Complete administrative overview of your organization's photo archives, folder access permissions, and collaborator directory."
            : isManager
              ? "Manage your assigned photo collections, review collaborator access permissions, and organize incoming media."
              : "Review your accessible team collections and quickly search archives for faces and moments."
          }
        </p>
      </div>

      <!-- User Identity Hub Card -->
      <div style="background: var(--card); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg, 16px); padding: 28px; margin-bottom: 32px; box-shadow: var(--shadow-sm);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 20px;">
          <div style="display: flex; align-items: center; gap: 20px;">
            <img 
              src="${avatarUrl}" 
              alt="${displayName}" 
              class="avatar-circle" 
              style="width: 72px; height: 72px; object-fit: cover; border: 2px solid var(--border-subtle);" 
            />
            <div>
              <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 4px;">
                <h2 style="font-size: 22px; font-weight: 700; margin: 0; color: var(--ink-primary);">${displayName}</h2>
                ${renderHighlighterPill({ text: roleTitle, variant: rolePillVariant })}
              </div>
              <div style="font-size: 14px; color: var(--ink-secondary); margin-bottom: 8px;">${displayEmail}</div>
              <div style="display: flex; align-items: center; gap: 12px; font-size: 12px; color: var(--ink-muted);">
                <span>Active Organization: <strong>${currentOrg}</strong></span>
                <span>&bull;</span>
                <span>Tenant ID: <code>${currentTenantId}</code></span>
              </div>
            </div>
          </div>

          <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            <button type="button" class="btn-secondary" id="dash-switch-org-btn" style="min-height: 42px; padding: 0 16px; font-size: 13px;">
              Switch Organization
            </button>
            <button type="button" class="btn-secondary" id="dash-signout-btn" style="min-height: 42px; padding: 0 16px; font-size: 13px; color: #E11D48;">
              Sign Out
            </button>
          </div>
        </div>
      </div>

      <!-- Multi-Tenant Organization Switcher Banner -->
      <div style="background: var(--card); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg, 16px); padding: 24px; margin-bottom: 32px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <div>
            <h3 style="font-size: 17px; font-weight: 700; margin: 0 0 4px 0; color: var(--ink-primary);">Your Organization Memberships</h3>
            <p style="font-size: 13px; color: var(--ink-secondary); margin: 0;">Switch active context. Permissions, galleries, and search scopes adapt instantaneously.</p>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px;">
          ${availableTenants.map(t => {
            const isCurrent = t.tenant_id === currentTenantId;
            const initials = t.initials || t.organization_name.substring(0, 2).toUpperCase();
            const tColor = t.theme_color || "var(--pill-mint-bg)";

            return `
              <div 
                style="
                  display: flex; 
                  align-items: center; 
                  justify-content: space-between; 
                  padding: 14px 16px; 
                  border: 1px solid ${isCurrent ? "var(--ink-primary)" : "var(--border-subtle)"}; 
                  border-radius: 12px; 
                  background: ${isCurrent ? "rgba(217, 239, 230, 0.25)" : "var(--surface-muted, #FAFAFA)"}; 
                  cursor: pointer;
                  transition: all 0.15s ease;
                "
                onclick="window.selectWorkspace('${t.tenant_id}')"
                role="button"
                tabindex="0"
                aria-label="Switch to ${t.organization_name}"
              >
                <div style="display: flex; align-items: center; gap: 12px;">
                  <div style="width: 36px; height: 36px; border-radius: 50%; background: ${tColor}; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;">
                    ${initials}
                  </div>
                  <div>
                    <div style="font-weight: 700; font-size: 14px; color: var(--ink-primary);">${t.organization_name}</div>
                    <div style="font-size: 12px; color: var(--ink-muted);">${t.role}</div>
                  </div>
                </div>

                ${isCurrent ? `
                  <span style="font-size: 12px; font-weight: 700; color: #10B981; display: flex; align-items: center; gap: 4px;">
                    Active
                  </span>
                ` : `
                  <span style="font-size: 12px; color: var(--ink-secondary);">Switch &rarr;</span>
                `}
              </div>
            `;
          }).join("")}
        </div>
      </div>

      <!-- Role-Governed Collections Matrix -->
      <div style="background: var(--card); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg, 16px); padding: 28px; margin-bottom: 32px; box-shadow: var(--shadow-sm);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; margin-bottom: 24px;">
          <div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <h3 style="font-size: 20px; font-weight: 700; margin: 0; color: var(--ink-primary);">
                ${isAdmin ? "Organization Collections Inventory" : isManager ? "Collections You Manage" : "Your Permitted Collections"}
              </h3>
              <span class="hl-pill neutral" style="font-size: 11px;">${displayedFolders.length} Accessible</span>
            </div>
            <p style="font-size: 13px; color: var(--ink-secondary); margin: 4px 0 0 0;">
              ${isAdmin 
                ? "Full inventory of all photo collections within this workspace. You have complete create, edit, and deletion authority."
                : isManager
                  ? "Collections where you have manager rights. You can grant access, upload photos, and review members."
                  : "Collections currently shared with your account. You can view, search, or upload as permitted."
              }
            </p>
          </div>

          <!-- Role-Differentiated Actions -->
          <div style="display: flex; gap: 10px; align-items: center;">
            ${(isAdmin || isManager) ? `
              <button 
                type="button" 
                class="btn-pill-black" 
                id="dash-create-collection-btn"
                style="min-height: 40px; padding: 0 18px; font-size: 13px;"
              >
                + Create Collection
              </button>
            ` : ""}

            ${isAdmin ? `
              <button 
                type="button" 
                class="btn-secondary" 
                id="dash-invite-member-btn"
                style="min-height: 40px; padding: 0 16px; font-size: 13px; border-color: var(--ink-primary);"
              >
                Invite Collaborator
              </button>
            ` : ""}
          </div>
        </div>

        ${isLoadingFolders ? `
          <div style="padding: 40px; text-align: center; color: var(--ink-muted);">
            <div class="editorial-loading-spinner" style="margin: 0 auto 12px auto;"></div>
            <p style="font-size: 14px;">Loading collection permissions...</p>
          </div>
        ` : displayedFolders.length === 0 ? `
          <div style="padding: 48px; text-align: center; border: 1px dashed var(--border-subtle); border-radius: 12px; background: var(--surface-muted, #FAFAFA);">
            <div style="font-size: 14px; font-weight: 600; color: #64748B; margin-bottom: 8px;">No Collections</div>
            <h4 style="font-size: 16px; font-weight: 700; margin: 0 0 6px 0;">No collections found</h4>
            <p style="font-size: 13px; color: var(--ink-secondary); margin: 0 0 18px 0;">
              ${isAdmin || isManager 
                ? "Get started by creating your first photo collection." 
                : "You have not been granted access to any photo collections yet. Contact your workspace administrator."
              }
            </p>
            ${(isAdmin || isManager) ? `
              <button type="button" class="btn-pill-black" onclick="window.openCreateAlbumModal?.()" style="min-height: 38px; padding: 0 16px; font-size: 13px;">
                Create Collection Now
              </button>
            ` : ""}
          </div>
        ` : `
          <!-- Accessible Collections Table -->
          <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 14px;">
              <thead>
                <tr style="border-bottom: 1px solid var(--border-subtle); color: var(--ink-muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
                  <th style="padding: 12px 16px;">Collection Name</th>
                  <th style="padding: 12px 16px;">Privacy Scope</th>
                  <th style="padding: 12px 16px;">Your Access Level</th>
                  <th style="padding: 12px 16px;">Photos</th>
                  <th style="padding: 12px 16px; text-align: right;">Available Actions</th>
                </tr>
              </thead>
              <tbody>
                ${displayedFolders.map(folder => {
                  const accessLvl = (folder.effective_access || (isAdmin ? "manager" : "viewer")).toLowerCase();
                  const isRestricted = folder.visibility === "restricted";
                  const canManageThis = isAdmin || folder.can_manage || accessLvl === "manager";
                  const canDeleteThis = isAdmin || folder.can_delete;

                  return `
                    <tr style="border-bottom: 1px solid var(--border-subtle); transition: background-color 0.15s ease;">
                      <td style="padding: 16px; font-weight: 600; color: var(--ink-primary);">
                        <div style="display: flex; align-items: center; gap: 10px;">
                          
                          <div>
                            <div>${folder.folder_name}</div>
                            ${folder.description ? `<div style="font-size: 12px; color: var(--ink-secondary); font-weight: 400; margin-top: 2px;">${folder.description}</div>` : ""}
                          </div>
                        </div>
                      </td>
                      <td style="padding: 16px;">
                        <span class="hl-pill ${isRestricted ? "butter" : "mint"}" style="font-size: 11px;">
                          ${isRestricted ? "Restricted ACL" : "Workspace-Wide"}
                        </span>
                      </td>
                      <td style="padding: 16px;">
                        <span class="hl-pill ${canManageThis ? "mint" : folder.can_upload ? "butter" : "neutral"}" style="font-size: 11px;">
                          ${canManageThis ? "Manager (Full Rights)" : folder.can_upload ? "Uploader" : "Viewer & Search"}
                        </span>
                      </td>
                      <td style="padding: 16px; font-variant-numeric: tabular-nums; color: var(--ink-secondary);">
                        ${(folder.photo_count || 0).toLocaleString()} items
                      </td>
                      <td style="padding: 16px; text-align: right;">
                        <div style="display: flex; gap: 8px; justify-content: flex-end; align-items: center;">
                          <button 
                            type="button" 
                            class="btn-secondary" 
                            style="min-height: 32px; padding: 0 10px; font-size: 12px;"
                            onclick="window.searchInFolder('${folder.folder_name}')"
                            title="Search within this collection"
                          >
                            Search
                          </button>

                          <button 
                            type="button" 
                            class="btn-secondary" 
                            style="min-height: 32px; padding: 0 10px; font-size: 12px;"
                            onclick="window.uploadToFolder('${folder.folder_name}')"
                            title="Upload photos directly into this collection"
                          >
                            Upload
                          </button>

                          ${canManageThis ? `
                            <button 
                              type="button" 
                              class="btn-secondary open-folder-permissions-btn" 
                              style="min-height: 32px; padding: 0 10px; font-size: 12px;"
                              data-folder-id="${folder.folder_id}"
                              data-folder-name="${folder.folder_name}"
                              title="Inspect and edit member access permissions"
                            >
                              Access (${isManager ? "Who Else Can View" : "Manage Access"})
                            </button>
                          ` : ""}

                          ${canDeleteThis ? `
                            <button 
                              type="button" 
                              class="btn-secondary delete-folder-dash-btn" 
                              style="min-height: 32px; padding: 0 10px; font-size: 12px; color: #E11D48; border-color: rgba(225, 29, 72, 0.3);"
                              data-folder-id="${folder.folder_id}"
                              data-folder-name="${folder.folder_name}"
                              title="Delete collection"
                            >
                              Delete
                            </button>
                          ` : ""}
                        </div>
                      </td>
                    </tr>
                  `;
                }).join("")}
              </tbody>
            </table>
          </div>
        `}
      </div>

      ${isAdmin ? `
        <!-- Admin-Only Workspace Members Directory -->
        <div style="background: var(--card); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg, 16px); padding: 28px; margin-bottom: 32px; box-shadow: var(--shadow-sm);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 12px;">
            <div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <h3 style="font-size: 20px; font-weight: 700; margin: 0; color: var(--ink-primary);">Workspace Collaborators &amp; Roles</h3>
                <span class="hl-pill mint" style="font-size: 11px;">Admin View</span>
              </div>
              <p style="font-size: 13px; color: var(--ink-secondary); margin: 4px 0 0 0;">
                Review all accounts active in <strong>${currentOrg}</strong> and their organization-level privileges.
              </p>
            </div>

            <button type="button" class="btn-secondary" id="dash-invite-member-sec-btn" style="min-height: 38px; padding: 0 16px; font-size: 13px;">
              + Invite New Member
            </button>
          </div>

          <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 14px;">
              <thead>
                <tr style="border-bottom: 1px solid var(--border-subtle); color: var(--ink-muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
                  <th style="padding: 12px 16px;">Collaborator</th>
                  <th style="padding: 12px 16px;">Email</th>
                  <th style="padding: 12px 16px;">Tenant Role</th>
                  <th style="padding: 12px 16px;">Status</th>
                </tr>
              </thead>
              <tbody>
                ${members.length > 0 ? members.map(m => `
                  <tr style="border-bottom: 1px solid var(--border-subtle);">
                    <td style="padding: 14px 16px; font-weight: 600; color: var(--ink-primary);">
                      <div style="display: flex; align-items: center; gap: 10px;">
                        <div style="width: 32px; height: 32px; border-radius: 50%; background: var(--surface-muted); border: 1px solid var(--border-subtle); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700;">
                          ${m.username.substring(0, 2).toUpperCase()}
                        </div>
                        <span>${m.username}</span>
                      </div>
                    </td>
                    <td style="padding: 14px 16px; color: var(--ink-secondary);">${m.email}</td>
                    <td style="padding: 14px 16px;">
                      <span class="hl-pill ${m.role === 'owner' || m.role === 'admin' ? 'mint' : m.role === 'contributor' ? 'butter' : 'neutral'}" style="font-size: 11px;">
                        ${m.role}
                      </span>
                    </td>
                    <td style="padding: 14px 16px;">
                      <span style="font-size: 12px; color: #10B981; font-weight: 600;">Active</span>
                    </td>
                  </tr>
                `).join("") : `
                  <tr>
                    <td colspan="4" style="padding: 24px; text-align: center; color: var(--ink-muted);">
                      No other team members listed for this organization.
                    </td>
                  </tr>
                `}
              </tbody>
            </table>
          </div>
        </div>
      ` : ""}
    </div>
  `;
}

