# Visual Search API — Comprehensive Endpoints, Inputs & Architectural Audit

This document provides an exhaustive, field-by-field audit of all **34 production API endpoints** in the Visual Search platform. 

For every endpoint, this document details:
1. **Inputs Taken**: Header, path, query, form, and JSON body parameters with data types and constraints.
2. **Why It Is Taken**: The functional, business, or security rationale for each input.
3. **Critical Audit & Verdict**: An evaluation of whether each input is **Genuinely Required**, **Redundant/Removable**, **Vulnerable/Needs Modification**, or if **Additional Inputs Should Be Added**.

---

## Table of Contents
- [1. Authentication & Multi-Tenant Membership (8 Endpoints)](#1-authentication--multi-tenant-membership)
- [2. Tenant Administration & Member Management (4 Endpoints)](#2-tenant-administration--member-management)
- [3. Folder Management & Access Control ACL (7 Endpoints)](#3-folder-management--access-control-acl)
- [4. Photo Upload & Ingestion (4 Endpoints)](#4-photo-upload--ingestion)
- [5. AI Vector Processing & Face Clustering (5 Endpoints)](#5-ai-vector-processing--face-clustering)
- [6. Visual & Multi-Angle Search (2 Endpoints)](#6-visual--multi-angle-search)
- [7. System Observability & Telemetry (2 Endpoints)](#7-system-observability--telemetry)
- [8. Executive Architecture Recommendations & Action Matrix](#8-executive-architecture-recommendations)

---

## 1. Authentication & Multi-Tenant Membership

### 1.1 `POST /api/auth/register-tenant`
* **Purpose**: Founding administrator registration. Atomically provisions a new organization workspace (`tenants` table) and assigns the creator as `owner`.
* **Inputs Taken**:
  | Input | Location | Type / Format | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `username` | Body (JSON) | `str` (3–50 chars, `^[a-zA-Z0-9_\-]+$`) | Required | Unique handle for the owner inside the new workspace. |
  | `email` | Body (JSON) | `str` (regex email) | Required | Owner contact & login identifier. |
  | `password` | Body (JSON) | `str` ($\ge 8$ chars) | Required | Plaintext password to be bcrypt-hashed ($12$ rounds). |
  | `organization_name`| Body (JSON) | `str` (2–100 chars) | Required | Business/studio display name (e.g., "Acme Photography"). |
  | `ignore_pending_invite` | Body (JSON) | `bool` | `False` | Safety override if user was previously invited to another tenant. |

* **Why It Is Taken**:
  * `organization_name`: Strictly required to create the root tenant record. Decoupling tenant creation from generic user signup guarantees no "orphan tenants" exist without names.
  * `ignore_pending_invite`: Prevents users from accidentally creating an unintended new studio when their employer/collaborator already sent them an invite link.
* **Critical Audit & Verdict**:
  * **`username`, `email`, `password`, `organization_name`**: **Genuinely Required**.
  * **`ignore_pending_invite`**: **Genuinely Required**. Crucial UX guard for multi-tenant onboarding.
  * **Recommendation / Missing**: Add an optional `workspace_slug: Optional[str] = None` (URL-friendly alias like `acme-studio`). If omitted, auto-generate from `organization_name`.

---

### 1.2 `GET /api/auth/invites/{invite_token}`
* **Purpose**: Public invite preview screen. Allows frontend to render: *"Alex has invited you to join Acme Studios as Editor"*.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `invite_token` | Path | `str` (UUIDv4 hex) | Required | Cryptographically secure invite token from the email link. |

* **Why It Is Taken**:
  * `invite_token`: Looked up in `tenant_invites` bypassing RLS. Returns the target studio name, pre-assigned role, and locked email address without exposing database IDs.
* **Critical Audit & Verdict**:
  * **`invite_token`**: **Genuinely Required**.
  * **Security Check**: Verified that password hashes and tenant secrets are omitted from the response (`InvitePreviewResponse` only returns `email`, `organization_name`, `role`, `expires_at`, and `initial_folders_count`).

---

### 1.3 `POST /api/auth/accept-invite`
* **Purpose**: Invited member onboarding. Finalizes registration directly into an existing organization.
* **Inputs Taken**:
  | Input | Location | Type / Format | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `invite_token` | Body (JSON) | `str` | Required | Valid, unexpired, unaccepted invite token. |
  | `username` | Body (JSON) | `str` (3–50 chars) | Required | Member's display handle in the studio. |
  | `password` | Body (JSON) | `str` ($\ge 8$ chars) | Required | Plaintext password to hash and store. |

* **Why It Is Taken**:
  * Does **NOT** take `email`: By extracting email directly from the verified invite database record, this endpoint prevents "invite link hijacking" (where user B intercepts user A's link and registers with user B's email).
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required & Secure**.
  * **Atomic Actions Verified**: Binds account to `invite.tenant_id`, assigns `invite.role`, pre-populates `folder_user_access` from `initial_folder_ids`, and sets `accepted_at = NOW()`.

---

### 1.4 `POST /api/auth/login`
* **Purpose**: Unified login endpoint for all users (owners, admins, contractors, viewers).
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `email` | Body (JSON) | `str` (email) | Required | User's email address. |
  | `password` | Body (JSON) | `str` | Required | User's plaintext password. |
  | `tenant_id` | Body (JSON) | `Optional[str]` | `None` | Target workspace identifier if the user belongs to multiple studios. |

* **Why It Is Taken**:
  * `tenant_id`: Because freelancers can belong to Studio A and Studio B with the same email, omitting `tenant_id` triggers disambiguation (`MultiTenantLoginResponse` with `available_tenants`). Supplying `tenant_id` logs the user straight into that studio.
* **Critical Audit & Verdict**:
  * **`email`, `password`**: **Genuinely Required**.
  * **`tenant_id`**: **Genuinely Required**. Solves multi-tenant account collision cleanly.
  * **Recommendation**: Allow `email` field to accept either email OR username for single-tenant users.

---

### 1.5 `POST /api/auth/switch-tenant`
* **Purpose**: Workspace switcher for multi-studio freelancers without logging out.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Active session token of the user. |
  | `tenant_id` | Body (JSON) | `str` | Required | Target organization `tenant_id` to switch into. |

* **Why It Is Taken**:
  * Validates that the caller's email genuinely has an active account in the target `tenant_id`. Issues a new JWT containing the target tenant's specific role and tenant claim.
* **Critical Audit & Verdict**:
  * **`tenant_id`**: **Genuinely Required**.
  * **Security Check**: Enforces explicit authorization check (`PermissionError` if user is not a member of target tenant).

---

### 1.6 `GET /api/auth/me`
* **Purpose**: Current session introspection and user profile retrieval.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | User session token. |

* **Why It Is Taken**:
  * Self-contained. All identity context (`user_id`, `tenant_id`, `role`) is extracted from the verified token and live Redis/Postgres user record.
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**. No redundant parameters.

---

### 1.7 `POST /api/auth/storage-config`
* **Purpose**: Configure custom AWS S3 storage bucket for asset storage.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | User session token. |
  | `s3_bucket` | Body (JSON) | `Optional[str]` | `None` | S3 bucket name override (defaults to server default). |

* **Why It Is Taken**:
  * Allows a user or studio to configure their own dedicated S3 bucket (BYO-S3). Runs `ping_s3(bucket)` to test connectivity before saving.
* **Critical Audit & Verdict**:
  * **Vulnerability Warning / Needs Change**: Currently, **any authenticated user** (even a `viewer`) can call `POST /api/auth/storage-config` and change their profile's bucket.
  * **Recommended Action**: 
    1. Restrict this endpoint to `require_tenant_admin` (`owner` or `admin`).
    2. Move this from `/api/auth/storage-config` to `/api/tenant/storage-config` because object storage in multi-tenant SaaS belongs to the organization, not individual user accounts.

---

### 1.8 `GET /api/auth/storage-config`
* **Purpose**: Check current S3 bucket configuration status.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | User session token. |

* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**. Returns bucket name and whether storage is configured without leaking secret keys.

---

## 2. Tenant Administration & Member Management

### 2.1 `GET /api/tenant/members`
* **Purpose**: Retrieve the organization roster (all members and roles).
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Must have `owner` or `admin` role. |

* **Why It Is Taken**:
  * Scoped automatically to the caller's `tenant_id`.
* **Critical Audit & Verdict**:
  * **Current Inputs**: **Genuinely Required**.
  * **Missing Inputs (Action Required)**: Lacks pagination parameters (`limit: int = 50`, `offset: int = 0`). If an enterprise tenant has 5,000 members, returning all rows in a single unbounded list will introduce network serialization lag and memory pressure.

---

### 2.2 `POST /api/tenant/invites`
* **Purpose**: Dispatch an invitation email/link to add a new member.
* **Inputs Taken**:
  | Input | Location | Type / Enum | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Must be `owner` or `admin`. |
  | `email` | Body (JSON) | `str` (email) | Required | Recipient's email address. |
  | `role` | Body (JSON) | `TenantRole` (`admin`, `editor`, `contributor`, `viewer`) | `"viewer"` | Organization base role granted upon acceptance. |
  | `initial_folder_ids` | Body (JSON) | `List[str]` | `[]` | Pre-assigned folder IDs granted on registration. |
  | `initial_access_level` | Body (JSON) | `FolderAccessLevel` | `"viewer"` | Access level for the pre-assigned folders. |

* **Why It Is Taken**:
  * `initial_folder_ids` & `initial_access_level`: Directly eliminates "admin fatigue". When inviting a freelance retoucher, the admin can grant access to `wedding_2026` immediately upon invite rather than waiting for them to sign up first.
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.
  * **Validation Rule Added**: Added check to prevent inviting someone as `owner` (tenants can only have one owner; ownership transfers require a dedicated flow).

---

### 2.3 `PATCH /api/tenant/members/{user_id}/role`
* **Purpose**: Update a member's organization base role (e.g. promote `contributor` $\to$ `editor`).
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Must be `owner` or `admin`. |
  | `user_id` | Path | `str` (UUID) | Required | Member to promote/demote. |
  | `role` | Body (JSON) | `TenantRole` | Required | New base role (`admin`, `editor`, `contributor`, `viewer`). |

* **Why It Is Taken**:
  * `user_id` in path identifies the target member. Enforces rule that the `owner` role cannot be modified by another admin.
  * Immediately evicts `user_auth:{tenant_id}:{user_id}` in Redis so the role change is instant.
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**. Clean RESTful design.

---

### 2.4 `DELETE /api/tenant/members/{user_id}`
* **Purpose**: Remove a member from the organization workspace.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Must be `owner` or `admin`. |
  | `user_id` | Path | `str` (UUID) | Required | Target member to remove. |

* **Why It Is Taken**:
  * Self-removal is blocked (caller cannot remove themselves). Owner cannot be removed. Database preserves uploaded photos via `ON DELETE SET NULL`.
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.

---

## 3. Folder Management & Access Control (ACL)

### 3.1 `POST /api/folders`
* **Purpose**: Create a new photo album/folder.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Role must be `owner`, `admin`, `editor`, or `contributor`. |
  | `folder_name` | Body (JSON) | `str` (1–100 chars) | Required | Display name of the folder (e.g., `wedding_portraits`). |
  | `description` | Body (JSON) | `Optional[str]` | `None` | Optional notes or description. |
  | `visibility` | Body (JSON) | `FolderVisibility` | `"restricted"` | `"tenant_wide"` (all team members) or `"restricted"` (explicit ACL only). |

* **Why It Is Taken**:
  * `visibility`: Controls whether 50 studio members inherit access automatically or if access requires explicit per-user grants.
  * Atomically grants the creator `manager` access to solve the "Orphaned Creator Bug".
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.
  * **Constraint**: `folder_name` is validated to be unique per tenant (`idx_pg_folders_tenant_name`).

---

### 3.2 `GET /api/folders`
* **Purpose**: List all folders accessible to the calling user.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Any authenticated user. |

* **Why It Is Taken**:
  * Uses the **Single-Query Permission Resolver** (`resolve_user_accessible_folders`). Evaluates tenant role, folder visibility, and explicit `folder_user_access` rows in one SQL query.
* **Critical Audit & Verdict**:
  * **Current Inputs**: **Genuinely Required**.
  * **Missing Inputs (Action Required)**: Add optional filtering and pagination:
    * `visibility: Optional[str] = Query(None)`
    * `limit: int = Query(50, ge=1, le=200)`
    * `offset: int = Query(0, ge=0)`

---

### 3.3 `GET /api/folders/{folder_id}`
* **Purpose**: Inspect folder metadata, photo count, and caller's specific capabilities (`can_upload`, `can_delete`, `can_manage`).
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Any authenticated user. |
  | `folder_id` | Path | `str` | Required | Target folder ID (or folder name). |

* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**. Enforces 403 Forbidden if caller has `revoked` or lacks access.

---

### 3.4 `PATCH /api/folders/{folder_id}`
* **Purpose**: Rename folder, update description, or change visibility.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Requires `manager` capability. |
  | `folder_id` | Path | `str` | Required | Target folder ID. |
  | `folder_name` | Body (JSON) | `Optional[str]` | `None` | New folder name. |
  | `description` | Body (JSON) | `Optional[str]` | `None` | New description text. |
  | `visibility` | Body (JSON) | `Optional[FolderVisibility]` | `None` | Switch between `tenant_wide` and `restricted`. |

* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**. Enforces name uniqueness check before updating.

---

### 3.5 `DELETE /api/folders/{folder_id}`
* **Purpose**: Delete a folder and remove its permissions.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Requires `manager` capability. |
  | `folder_id` | Path | `str` | Required | Folder to delete. |

* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.

---

### 3.6 `POST /api/folders/{folder_id}/access`
* **Purpose**: Grant, update, or revoke access for a single member on a folder.
* **Inputs Taken**:
  | Input | Location | Type / Enum | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Caller must have `manager` capability on this folder. |
  | `folder_id` | Path | `str` | Required | Target folder ID. |
  | `user_id` | Body (JSON) | `str` (UUID) | Required | Member whose access is being configured. |
  | `access_level` | Body (JSON) | `FolderAccessLevel` (`inherit`, `revoked`, `viewer`, `uploader`, `editor`, `manager`) | Required | Access level granted. |

* **Why It Is Taken**:
  * Setting `access_level = "revoked"` allows an admin to explicitly block a specific contractor from a `tenant_wide` folder without converting the entire album to restricted.
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.

---

### 3.7 `POST /api/folders/access/bulk`
* **Purpose**: Multi-user, multi-folder batch access assignment in a single HTTP request.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Must be admin or manager of all target folders. |
  | `folder_ids` | Body (JSON) | `List[str]` ($\ge 1$) | Required | Target folder IDs. |
  | `user_ids` | Body (JSON) | `List[str]` ($\ge 1$) | Required | Target member IDs. |
  | `access_level` | Body (JSON) | `FolderAccessLevel` | Required | Access level applied across all pairs. |

* **Why It Is Taken**:
  * High-throughput enterprise endpoint. Assigning 10 photographers to 5 event folders takes 1 API call instead of 50 consecutive roundtrips.
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.
  * **Optimization Check**: Uses PostgreSQL bulk `INSERT ... ON CONFLICT DO UPDATE` executing in $<5\text{ms}$.

---

### 3.8 `DELETE /api/folders/{folder_id}/access/{user_id}`
* **Purpose**: Delete explicit ACL record for a user (falls back to tenant role / folder visibility).
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Caller must have `manager` access. |
  | `folder_id` | Path | `str` | Required | Folder ID. |
  | `user_id` | Path | `str` | Required | Member ID whose explicit grant is deleted. |

* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.

---

### 3.9 `GET /api/folders/{folder_id}/members`
* **Purpose**: View all members with explicit access grants on a specific folder.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Caller must have `manager` access. |
  | `folder_id` | Path | `str` | Required | Folder ID. |

* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**. Returns username, email, base role, and folder access level.

---

## 4. Photo Upload & Ingestion

### 4.1 `POST /api/upload/photo`
* **Purpose**: Upload and ingest a single image asset.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Caller must have `upload` capability on the folder. |
  | `file` | Form/Multipart | `Optional[UploadFile]` | `None` | Raw image file upload. |
  | `image_url` | Form | `Optional[str]` | `None` | Public or S3 URL to ingest from directly. |
  | `folder_name` | Form | `str` | `"general"` | Destination folder/album name. |
  | `s3_bucket` | Form | `Optional[str]` | `None` | **Target S3 bucket override.** |

* **Why It Is Taken**:
  * Either `file` or `image_url` must be provided. Validates image size ($\le 20\text{ MB}$) and format.
* **Critical Audit & Verdict**:
  * **`file` / `image_url`**: **Genuinely Required**.
  * **`folder_name`**: **Genuinely Required**.
  * **`s3_bucket` (CRITICAL FLAW — SHOULD BE REMOVED)**:
    * Allowing a client to specify `s3_bucket` in a Form field poses a **tenant data exfiltration / injection vulnerability**. An authenticated user from Studio A could pass `s3_bucket=studio-b-bucket` and pollute or probe other storage buckets.
    * **Action**: Deprecate and remove `s3_bucket` from the client Form request. The backend must strictly resolve the bucket from the tenant profile or server environment via `resolve_user_s3_bucket()`.

---

### 4.2 `POST /api/upload/batch`
* **Purpose**: Ingest up to 50 photos in a single HTTP `multipart/form-data` request.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Caller must have `upload` permission. |
  | `files` | Form/Multipart | `List[UploadFile]` (1–50) | Required | Array of image files. |
  | `folder_name` | Form | `str` | `"general"` | Destination album. |
  | `s3_bucket` | Form | `Optional[str]` | `None` | **Target S3 bucket override.** |

* **Critical Audit & Verdict**:
  * **`files`**: **Genuinely Required**. Capped at $\le 50$ images per request to prevent HTTP timeouts.
  * **`folder_name`**: **Genuinely Required**.
  * **`s3_bucket`**: **REMOVE**. Identical security risk as in `4.1`. Must be resolved server-side from `tenant_id`.

---

### 4.3 `POST /api/upload/from-s3-prefix`
* **Purpose**: Ingest and index photos directly from an existing S3 folder prefix.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Caller must have `upload` permission. |
  | `folder_name` | Form | `str` | Required | S3 folder prefix to scan. |
  | `s3_bucket` | Form | `Optional[str]` | `None` | S3 bucket name. |

* **Critical Audit & Verdict**:
  * **`folder_name`**: **Genuinely Required**.
  * **`s3_bucket`**: Make this strictly restricted to `owner` or `admin`. Regular `contributor` accounts should not be permitted to point the backend crawler to arbitrary S3 buckets.

---

### 4.4 `GET /ui`
* **Purpose**: Serves the interactive Web Batch Uploader HTML/JS page.
* **Inputs Taken**: None (GET HTML page).
* **Critical Audit & Verdict**:
  * **Genuinely Required** for visual browser-based testing and batch image indexing.

---

## 5. AI Vector Processing & Face Clustering

### 5.1 `POST /api/process/image/{image_id}`
* **Purpose**: Runs AI feature extraction (ArcFace face embeddings + CLIP scene vectors) and indexes into tenant FAISS stores.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Authenticated user. |
  | `image_id` | Path | `str` | Required | Unique ID of previously uploaded image (`meta:{image_id}`). |

* **Why It Is Taken**:
  * Binds processing strictly to the caller's tenant. Reads the image from local storage or S3, detects faces, extracts vectors, and upserts into FAISS.
* **Critical Audit & Verdict**:
  * **`image_id`**: **Genuinely Required**.

---

### 5.2 `POST /api/clusters/generate`
* **Purpose**: Run HDBSCAN clustering over all extracted face vectors to group identities into named people albums.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Authenticated user. |
  | `folder_name` | Query | `str` | Required | Target album to cluster. |
  | `min_cluster_size` | Query | `int` ($\ge 2$) | `3` | Minimum faces needed to form an identity group. |
  | `epsilon` | Query | `float` (0.01–1.0) | `0.25` | HDBSCAN cosine distance tolerance. |

* **Why It Is Taken**:
  * `min_cluster_size` & `epsilon`: Tune cluster granularity. Lower epsilon groups only near-identical angles; higher epsilon groups diverse lighting and angles.
* **Critical Audit & Verdict**:
  * **`folder_name`, `min_cluster_size`, `epsilon`**: **Genuinely Required**.
  * **Flaw / Improvement Needed**: Currently does not explicitly check `check_folder_capability(folder_name, "view")`. It should verify the caller has access to that folder before clustering its vectors.

---

### 5.3 `GET /api/clusters`
* **Purpose**: List all discovered people albums (identities).
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Authenticated user. |
  | `folder_name` | Query | `Optional[str]` | `None` | Filter identities to a specific album. |

* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**. Scoped to `tenant_id` automatically.

---

### 5.4 `PATCH /api/clusters/{cluster_id}`
* **Purpose**: Name an identity cluster (e.g., change "Cluster #12" to "Sarah Connor").
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Authenticated user. |
  | `cluster_id` | Path | `str` | Required | Unique cluster ID. |
  | `person_name` | Body (JSON) | `str` (1–100 chars) | Required | Human name assigned to the cluster. |

* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.

---

### 5.5 `GET /api/jobs/{job_id}`
* **Purpose**: Poll asynchronous batch ingestion or worker job progress.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Authenticated user. |
  | `job_id` | Path | `str` | Required | Unique job identifier. |

* **Why It Is Taken**:
  * Bounded by tenant context to prevent IDOR attacks (users cannot inspect jobs belonging to other tenants).
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.

---

## 6. Visual & Multi-Angle Search

### 6.1 `POST /api/search/image`
* **Purpose**: Primary semantic visual search and face recognition query.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Authenticated user. |
  | `file` | Form/Multipart | `Optional[UploadFile]` | `None` | Query image file upload. |
  | `image_url` | Form | `Optional[str]` | `None` | Query image URL. |
  | `folder_name` | Form / Query | `Optional[str]` | `None` | Restrict search strictly to this album. |
  | `top_k` | Query | `int` (1–30) | `20` | Max matches returned. |
  | `threshold` | Query | `float` (0.0–1.0) | `0.60` | Cosine similarity cutoff. |

* **Why It Is Taken**:
  * `folder_name`: If omitted, search automatically runs across **all folders the caller is permitted to view**, blocking folders with `revoked` access.
  * `top_k` capped at $30$ to keep response times under $35\text{ms}$.
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**.
  * **Ergonomics Check**: Accepts `folder_name` in either Form-data or Query parameter for flexibility with standard HTTP clients.

---

### 6.2 `POST /api/search/multi-angle`
* **Purpose**: High-precision face verification using multiple profile angles (front, left, right).
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `Authorization` | Header | `Bearer <JWT>` | Required | Authenticated user. |
  | `front_file` / `front_url` | Form/Multipart | `Optional[UploadFile / str]` | `None` | Frontal face view. |
  | `left_file` / `left_url` | Form/Multipart | `Optional[UploadFile / str]` | `None` | Left profile face view. |
  | `right_file` / `right_url`| Form/Multipart | `Optional[UploadFile / str]` | `None` | Right profile face view. |
  | `folder_name` | Form / Query | `Optional[str]` | `None` | Target album filter. |
  | `top_k` | Query | `int` (1–30) | `20` | Max matches. |
  | `threshold` | Query | `float` (0.0–1.0) | `0.60` | Minimum similarity score. |

* **Why It Is Taken**:
  * Fuses multiple feature vectors via cosine distance, reducing false positives in VIP/celebrity recognition.
* **Critical Audit & Verdict**:
  * **Inputs**: **Genuinely Required**. Requires at least one angle to contain a detectable face.

---

## 7. System Observability & Telemetry

### 7.1 `GET /api/health`
* **Purpose**: Container liveness, readiness, and load-balancer health probe.
* **Inputs Taken**: None.
* **Critical Audit & Verdict**:
  * **Genuinely Required**. Returns 200 OK with timestamp.

---

### 7.2 `POST /api/log`
* **Purpose**: Ingestion of frontend client-side telemetry, warnings, and unhandled errors.
* **Inputs Taken**:
  | Input | Location | Type | Default | Description |
  | :--- | :--- | :--- | :--- | :--- |
  | `payload` | Body (JSON) | `Dict[str, Any]` | Required | Event details; must contain `"event": str`. |

* **Why It Is Taken**:
  * Logs to structured logging (`loguru`) prefixed with `client.<event>`.
* **Critical Audit & Verdict**:
  * **`payload`**: **Genuinely Required**.
  * **Security Warning / Action Required**: Currently unauthenticated and without rate limiting. An external attacker could flood `POST /api/log` with massive payloads to exhaust server memory or disk log space.
  * **Action**: Add an IP-based rate limiter (e.g., 60 requests/minute) and validate that `payload` size does not exceed 16 KB.

---

## 8. Executive Architecture Recommendations

| Priority | Endpoint(s) | Parameter | Audit Finding | Recommended Action |
| :---: | :--- | :--- | :--- | :--- |
| 🔴 **HIGH** | `POST /api/upload/photo`<br/>`POST /api/upload/batch` | `s3_bucket: Optional[str]` | **Security Risk**: Untrusted client can override target storage bucket. | **Remove `s3_bucket` from Form body**. Resolve bucket strictly on the server from the caller's tenant profile. |
| 🔴 **HIGH** | `POST /api/auth/storage-config` | Endpoint permissions | **Permission Flaw**: Low-privilege users (`viewer`) can alter S3 configuration. | Restrict to `require_tenant_admin` (`owner`/`admin`) and relocate to `/api/tenant/storage-config`. |
| 🟡 **MEDIUM** | `GET /api/tenant/members`<br/>`GET /api/folders` | None (Unbounded lists) | **Scalability Risk**: Returns unbounded records; slow for enterprise studios. | Add standard pagination parameters: `limit: int = 50`, `offset: int = 0`. |
| 🟡 **MEDIUM** | `POST /api/log` | Unauthenticated endpoint | **DOS / Log Pollution Risk**: No body size limit or rate limiting. | Apply rate limiting (60 req/min/IP) and enforce 16 KB payload limit. |
| 🟢 **LOW** | `POST /api/clusters/generate` | `folder_name: str` | Missing ACL check before clustering. | Add `check_folder_capability(folder_name, "view")` guard. |

