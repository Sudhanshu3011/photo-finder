import { workspaceStore } from "../../stores/workspaceStore.js";
import { authStore } from "../../stores/authStore.js";
import { renderHighlighterPill } from "../primitives/HighlighterPill.js";

export function renderNavbar(props = {}) {
  const { currentTab = "home" } = props;
  const currentOrg = workspaceStore.getCurrentOrganizationName();
  const isAuthenticated = authStore.isAuthenticated();
  const authUser = authStore.getUser();

  const displayName = authUser?.username || "Authenticated Member";
  const displayEmail = authUser?.email || "";
  const displayRole = authUser?.role || workspaceStore.getCurrentRole() || "viewer";
  const avatarUrl = authUser?.avatarUrl || "";
  const initials = displayName.substring(0, 2).toUpperCase();

  const roleLower = displayRole.toLowerCase();
  const rolePillVariant = (roleLower.includes("owner") || roleLower.includes("admin")) 
    ? "mint" 
    : (roleLower.includes("manager") || roleLower.includes("editor")) 
      ? "butter" 
      : "rose";

  const navItems = isAuthenticated
    ? [
        { id: "profile", label: "Dashboard" },
        { id: "albums", label: "Collections" },
        { id: "search", label: "Search" },
        { id: "people", label: "People" },
        { id: "upload", label: "Upload" },
      ]
    : [
        { id: "home", label: "Home" },
        { id: "search", label: "Search" },
        { id: "people", label: "People" },
        { id: "upload", label: "Upload" },
        { id: "albums", label: "Collections" },
      ];

  return `
    <header>
      <nav class="site-nav" role="navigation" aria-label="Main Navigation">
        <!-- Brand Wordmark -->
        <div class="nav-brand" id="brand-home-btn" role="button" tabindex="0" aria-label="Velunara Home">
          <span>Velunara</span>
          <span style="font-weight: 400; font-size: 13px; color: var(--ink-secondary); margin-left: 6px; letter-spacing: 0.02em;">Workspace</span>
        </div>

        <!-- Desktop Navigation Links -->
        <div class="nav-menu" role="menubar">
          ${navItems.map(item => `
            <a 
              class="nav-link ${currentTab === item.id ? "active" : ""}" 
              data-tab="${item.id}"
              role="menuitem"
              tabindex="0"
              aria-current="${currentTab === item.id ? "page" : "false"}"
            >
              ${item.label}
            </a>
          `).join("")}
        </div>

        <!-- Actions: Auth / Workspace Controls -->
        <div class="nav-actions">
          ${isAuthenticated ? `
            <!-- Authenticated: Workspace Pill & Profile Dropdown -->
            <div 
              class="workspace-badge" 
              id="open-workspace-btn" 
              role="button" 
              tabindex="0" 
              aria-haspopup="dialog"
              aria-label="Current Workspace: ${currentOrg}. Click to switch."
              title="Switch workspace"
            >
              <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background-color: #10B981;" aria-hidden="true"></span>
              <span>${currentOrg}</span>
              <span style="font-size: 10px; opacity: 0.7;" aria-hidden="true">▾</span>
            </div>

            <!-- Profile Menu Dropdown -->
            <div class="user-profile-menu">
              <button 
                type="button" 
                class="user-profile-trigger" 
                id="user-profile-trigger"
                aria-haspopup="true"
                aria-expanded="false"
                aria-label="Account options for ${displayName}"
              >
                ${avatarUrl ? `
                  <img 
                    src="${avatarUrl}" 
                    alt="" 
                    class="avatar-circle" 
                    style="width: 30px; height: 30px; border: 1px solid var(--border-subtle);"
                  />
                ` : `
                  <div 
                    class="avatar-circle" 
                    style="width: 30px; height: 30px; border: 1px solid var(--border-subtle); background: var(--surface-muted); font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center;"
                  >
                    ${initials}
                  </div>
                `}
                <span style="font-size: 13px; font-weight: 600; color: var(--ink-primary);">${displayName}</span>
                <span style="font-size: 10px; color: var(--ink-secondary);">▾</span>
              </button>

              <div class="user-profile-dropdown" id="user-profile-dropdown" role="menu">
                <div style="padding: 6px 10px 10px 10px;">
                  <div style="font-weight: 700; font-size: 14px; color: var(--ink-primary);">${displayName}</div>
                  <div style="font-size: 12px; color: var(--ink-secondary); margin-bottom: 6px;">${displayEmail}</div>
                  <div>${renderHighlighterPill({ text: displayRole, variant: rolePillVariant })}</div>
                </div>
                <div class="dropdown-divider"></div>
                <button type="button" class="dropdown-item" id="menu-profile-dashboard-btn">
                  Profile &amp; Dashboard
                </button>
                <button type="button" class="dropdown-item" id="menu-switch-workspace-btn">
                  Switch Workspace
                </button>
                <button type="button" class="dropdown-item" id="menu-open-upload-btn">
                  Add New Photos
                </button>
                <div class="dropdown-divider"></div>
                <button type="button" class="dropdown-item" id="nav-signout-btn" style="color: #E11D48;">
                  Sign Out
                </button>
              </div>
            </div>
          ` : `
            <!-- Unauthenticated: Sign In & Create Workspace Actions -->
            <button 
              type="button" 
              class="btn-secondary" 
              id="nav-signin-btn" 
              style="min-height: 36px; padding: 4px 16px; font-size: 13px;"
            >
              Sign In
            </button>
            <button 
              type="button" 
              class="btn-pill-black" 
              id="nav-signup-btn" 
              style="min-height: 36px; padding: 4px 18px; font-size: 13px;"
            >
              Create Workspace
            </button>
          `}
        </div>
      </nav>
    </header>
  `;
}
