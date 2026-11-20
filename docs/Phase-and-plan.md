Phase-Wise Implementation Plan: User Dashboard, Security & Team Collaboration
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 IMPLEMENTATION ROADMAP                                 │
├──────────────────┬──────────────────┬──────────────────┬──────────────────┬────────────┤
│     PHASE 1      │     PHASE 2      │     PHASE 3      │     PHASE 4      │  PHASE 5   │
│ Client Auth &    │ Concurrency &    │ Role-Governed    │ Invitation       │ Multi-Modal│
│ Tenant State     │ Duplicate Name   │ Profile          │ Lifecycle        │ Search &   │
│ Hardening        │ Guard            │ Dashboard        │ (Send & Accept)  │ Perm. Scope│
└──────────────────┴──────────────────┴──────────────────┴──────────────────┴────────────┘
Phase 1: Client Authentication & Reactive Tenant State Hardening

Objective: Ensure JWT Bearer tokens and X-Tenant-ID headers reliably propagate across all HTTP requests, and implement clean multi-tenant switching with zero data leakage.

Tasks:
Fix apiClient Wiring in Browser Runtime:
Connect workspaceStore.js and workspaceStore.ts with apiClient.configure({ getToken, getTenantId, onUnauthorized }).
Resolves the 401 Unauthorized issue on /api/folders and /api/upload/batch.
Multi-Tenant Switching Service (POST /api/auth/switch-tenant):
Add switchTenant(targetTenantId) method in frontend/src/services/api/authApi.ts.
On successful switch, re-issue JWT token, update authStore, and flush all in-memory collections, cluster medoids, and search caches.
Dynamic Navbar Synchronization:
Update frontend/src/components/layout/Navbar.ts to display real-time organization name, initials badge, and role indicator pill (mint for Admin, butter for Manager, neutral for Viewer).
Files Modified/Created:
frontend/src/stores/workspaceStore.js & .ts
frontend/src/services/api/authApi.js & .ts
frontend/src/components/layout/Navbar.js & .ts
Verification Checkpoint:
Log in -> create folder -> confirm 201 Created with valid Bearer token.
Switch tenant -> confirm navbar badge updates and cached galleries reload.
Phase 2: Duplicate Folder Name Concurrency & Race-Condition Defense

Objective: Guarantee transactional integrity when multiple managers attempt to create folders with the identical name simultaneously.

Tasks:
Backend Conflict Guard Validation:
Verify PostgreSQL composite constraint CONSTRAINT uq_tenant_folder_name UNIQUE (tenant_id, folder_name).
In src/api/folder_routes.py, catch PostgreSQL IntegrityError / duplicate key violation and return 409 Conflict with a descriptive message.
Frontend Inline Conflict Interceptor:
In CreateAlbumDialog.ts and submitCreateAlbum, intercept 409 Conflict.
Highlight the collection name input in red and display human-centric validation:

"A collection named '{name}' already exists in this workspace. Please choose a distinct name."

Keep modal open so user does not lose their typed description or visibility settings.
Files Modified:
src/api/folder_routes.py
frontend/src/features/albums/CreateAlbumDialog.ts & .js
frontend/src/app.ts & .js
Verification Checkpoint:
Attempt to create two folders with the exact same name; verify the second request gracefully halts with the inline error.
Phase 3: Role-Differentiated Profile & Workspace Dashboard

Objective: Build the authenticated User Profile & Workspace Dashboard (#profile view) that dynamically adapts its layout and capabilities based on whether the active user is an Admin, Manager, or Regular User.

Tasks:
Build Profile Dashboard Component:
Create frontend/src/features/profile/ProfileDashboardPage.ts / .js.
Identity Card: Avatar, full name, email, active organization, and tenant role badge.
Organization Switcher Card: View all organization memberships with active status indicators and one-click switching.
Accessible Collections Grid: Lists all collections accessible to the user, with badges for effective access level (Manager, Uploader, Viewer).
Role-Specific Capabilities:
Admin / Owner View:
Full folder inventory (all collections in tenant).
Collection creation and deletion buttons.
"Invite Team Member" trigger button.
Tenant member directory overview.
Manager View:
Inventory of collections managed by user.
Collection creation button (auto-grants Manager).
Per-folder "Who else can edit/view" detail drawer (GET /api/folders/{id}/members).
Granular permissions modal trigger for owned folders.
Regular User (Contributor / Viewer) View:
Read-only permitted collections list with search badges.
Hidden administrative and invitation actions.
Navigation Integration:
Add view-profile section to frontend/src/app.ts.
Add "User Profile & Workspace Dashboard" to navbar user profile dropdown.
Files Modified/Created:
frontend/src/features/profile/ProfileDashboardPage.ts & .js
frontend/src/app.ts & .js
frontend/src/components/layout/Navbar.ts & .js
Verification Checkpoint:
Log in with different user roles and verify the dashboard strictly exposes the appropriate controls per Section 2 of USER_DASHBOARD_AND_SECURITY_SPEC.md.
Phase 4: Invitation Management Lifecycle (Send, Preview & Accept)

Objective: Implement secure team onboarding where authorized admins can invite team members and pre-assign initial folder access.

Tasks:
Admin Invite Modal:
Create frontend/src/features/profile/InviteMemberModal.ts / .js.
Fields: Invitee Email, Role dropdown (admin, contributor, viewer), Multi-select checklist of tenant collections to pre-grant, Initial Access Level (manager, uploader, viewer).
Wire to POST /api/tenant/invites.
Display copyable invitation link (https://.../#accept-invite?token=...) with toast alert.
Public Invitation Acceptance View:
Create frontend/src/features/auth/AcceptInvitePage.ts / .js.
Parse hash #accept-invite?token=....
Call GET /api/auth/invites/{token} to preview organization branding, invited email, and granted role.
Form: Full name and password creation.
Wire POST /api/auth/accept-invite.
Auto-hydrate new user session with returned JWT and redirect directly to the Profile Dashboard with pre-granted collections ready.
Files Modified/Created:
frontend/src/features/profile/InviteMemberModal.ts & .js
frontend/src/features/auth/AcceptInvitePage.ts & .js
frontend/src/services/api/tenantApi.ts & .js
frontend/src/app.ts & .js
Verification Checkpoint:
Generate an invite link from Admin dashboard -> open in incognito -> accept invite -> verify user is immediately logged in with the pre-assigned collections.
Phase 5: Multi-Modal Search Workbench & Permitted Folder Scope

Objective: Equip the Search Studio with dual-mode search (Portrait Image + Natural Language Text Query), strict folder permission dropdown, and a direct navigation shortcut.

Tasks:
Dual Search Modes in Search Workbench:
Mode A (Face Reference Image): Portrait file upload / drag-and-drop / medoid selection -> POST /api/search/image.
Mode B (Scene Query Text): Natural language semantic query ("Keynote speaker on stage", "VIP red carpet arrival") matching CLIP scene vectors.
Permitted Collections Dropdown:
Populate dropdown strictly with the user's accessible folders (allowed_folders), preventing vector cross-contamination.
Direct Navigation Shortcut:
Place banner/link under search scope dropdown:
html
<div class="search-scope-footer">
  <span>Need a new collection or need to invite collaborators?</span>
  <a href="#profile" class="editorial-link" id="nav-to-profile-dashboard">
    Go to Profile &amp; Workspace Dashboard &rarr;
  </a>
</div>
Clicking routes directly to the Profile Dashboard (data-tab="profile").
Files Modified:
frontend/src/app.ts & .js
frontend/src/services/api/searchApi.ts & .js
Verification Checkpoint:
Test searching within a restricted folder vs all permitted folders; verify the shortcut seamlessly opens the Profile Dashboard.
Phase 6: End-to-End Verification, Anti-Slop Audit & Asset Build

Objective: Comprehensive end-to-end verification of TypeScript compilation, Python backend tests, and Elementum design compliance.

Tasks:
Run tsc --noEmit --project frontend/tsconfig.json (0 type errors).
Run npm run build inside frontend/ to produce clean frontend/dist/.
Run python3 -m py_compile src/api/*.py main.py.
Validate mobile responsiveness, WCAG 44px touch targets, and contrast ratios.