/**
 * BatchUploadPage Feature Component
 * 50-photo drag-and-drop dropzone with pre-upload validation,
 * staging preview, target album selector, and Celery worker fleet toggle.
 * Adheres to Elementum editorial design, design-taste-frontend, and anti-slop rules.
 */

export interface StagedFileItem {
  id: string;
  file: File;
  previewUrl: string;
  name: string;
  sizeFormatted: string;
  isValid: boolean;
  error?: string;
}

export interface BatchUploadState {
  stagedFiles: StagedFileItem[];
  selectedFolder: string;
  useCelery: boolean;
  isDragging: boolean;
  validationError: string | null;
  folders: Array<{
    id: string;
    title: string;
    count?: number;
    can_upload?: boolean;
    can_manage?: boolean;
    effective_access?: string;
  }>;
  canCreateFolder?: boolean;
  userRole?: string;
  isUploading: boolean;
  uploadProgress: number;
  currentStage: string;
  jobId: string | null;
  completedSummary: {
    total: number;
    successful: number;
    failed: number;
    peopleCount: number;
  } | null;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".raw", ".cr2", ".nef", ".arw"];
export const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50MB
export const MAX_BATCH_COUNT = 50;

export function validateBatchFiles(files: File[]): { valid: StagedFileItem[]; error: string | null } {
  let errorMsg: string | null = null;
  if (files.length > MAX_BATCH_COUNT) {
    errorMsg = `Batch size limit is ${MAX_BATCH_COUNT} photos. Only the first ${MAX_BATCH_COUNT} files were selected.`;
  }

  const slice = files.slice(0, MAX_BATCH_COUNT);
  const staged: StagedFileItem[] = [];

  for (let i = 0; i < slice.length; i++) {
    const f = slice[i];
    const ext = "." + (f.name.split(".").pop() || "").toLowerCase();
    const isExtensionValid = ALLOWED_EXTENSIONS.includes(ext) || f.type.startsWith("image/");
    const isSizeValid = f.size <= MAX_FILE_SIZE_BYTES;

    let itemError: string | undefined = undefined;
    if (!isExtensionValid) {
      itemError = "Unsupported format (use JPG, PNG, WEBP, RAW)";
    } else if (!isSizeValid) {
      itemError = "Exceeds 50MB file size limit";
    }

    const previewUrl = isExtensionValid ? URL.createObjectURL(f) : "";

    staged.push({
      id: `f_${Date.now()}_${i}_${Math.random().toString(36).slice(2, 7)}`,
      file: f,
      previewUrl,
      name: f.name,
      sizeFormatted: formatFileSize(f.size),
      isValid: !itemError,
      error: itemError,
    });
  }

  return { valid: staged, error: errorMsg };
}

export function renderBatchUploadDropzone(state: BatchUploadState): string {
  const totalValid = state.stagedFiles.filter(f => f.isValid).length;
  const totalBytes = state.stagedFiles.reduce((acc, f) => acc + (f.isValid ? f.file.size : 0), 0);
  const totalSizeFormatted = formatFileSize(totalBytes);

  // Strictly filter folders where caller has upload capability
  const uploadPermittedFolders = state.folders.filter(f => f.can_upload !== false);
  const canCreateAlbum = state.canCreateFolder !== false;
  const hasUploadAccess = uploadPermittedFolders.length > 0;

  return `
    <div style="max-width: 900px; margin: 0 auto;">
      <!-- Section Header -->
      <div style="margin-bottom: 28px;">
        <span class="hl-pill mint" style="font-size: 12px; margin-bottom: 12px; display: inline-block;">Batch Ingestion &amp; Intelligence</span>
        <h1 style="font-size: clamp(28px, 3.8vw, 42px); line-height: 1.15; margin-bottom: 10px;">
          Add Photos to your Workspace
        </h1>
        <p style="font-size: 15px; color: var(--ink-secondary); max-width: 680px; line-height: 1.6;">
          Drag up to 50 photos directly into your organization workspace. Velunara detects identities, creates face vector signatures, and groups faces into your People directory automatically.
        </p>
      </div>

      <!-- Validation Error / Notice Banner -->
      ${state.validationError ? `
        <div style="background: #FFF7ED; border: 1px solid #FFEDD5; border-radius: 12px; padding: 14px 18px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; font-size: 14px; color: #9A3412;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span style="font-weight: 700;">Notice:</span>
            <span>${state.validationError}</span>
          </div>
          <button type="button" id="dismiss-upload-error-btn" style="background: none; border: none; font-size: 18px; cursor: pointer; color: #9A3412;">&times;</button>
        </div>
      ` : ""}

      <!-- Main Upload Control Card -->
      <div style="background: var(--card); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: 32px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02); margin-bottom: 32px;">
        
        <!-- Drag & Drop Zone -->
        <div 
          id="batch-dropzone" 
          class="batch-dropzone ${state.isDragging ? "dragging" : ""}"
          style="
            border: 2px dashed ${state.isDragging ? "var(--ink)" : "var(--border-subtle)"}; 
            border-radius: 16px; 
            padding: 48px 24px; 
            text-align: center; 
            cursor: pointer;
            background: ${state.isDragging ? "var(--mint-light, #F2FBF7)" : "var(--ground)"};
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
          "
        >
          <div style="width: 56px; height: 56px; margin: 0 auto 16px auto; background: var(--surface-muted); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 26px; border: 1px solid var(--border-subtle);">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>
          </div>
          <h3 style="font-size: 19px; font-weight: 600; margin-bottom: 8px;">
            Drag &amp; drop photos here
          </h3>
          <p style="font-size: 14px; color: var(--ink-muted); margin-bottom: 18px;">
            Supports up to 50 photos simultaneously · JPG, PNG, WEBP, RAW (up to 50MB per photo)
          </p>
          <input type="file" id="batch-file-input" multiple accept="image/*,.raw,.cr2,.nef,.arw" style="display: none;" />
          <button type="button" class="btn-secondary" id="browse-files-btn">
            Choose Photos from Computer
          </button>
        </div>

        <!-- Target Album & Processing Fleet Controls -->
        <div style="margin-top: 28px; display: grid; grid-template-columns: minmax(260px, 1fr) minmax(260px, 1fr); gap: 20px; align-items: end;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <label for="target-album-select" style="font-size: 13px; font-weight: 600; color: var(--ink);">
                Target Collection / Album
              </label>
              ${canCreateAlbum ? `
                <button type="button" id="open-create-album-btn" style="background: none; border: none; font-size: 12px; font-weight: 600; color: var(--ink); text-decoration: underline; cursor: pointer; padding: 0;">
                  + Create New Album
                </button>
              ` : `
                <span style="font-size: 11px; color: var(--ink-muted);">Role: ${state.userRole || "viewer"}</span>
              `}
            </div>
            ${hasUploadAccess ? `
              <select 
                id="target-album-select" 
                style="width: 100%; padding: 11px 14px; border-radius: 10px; border: 1px solid var(--border-subtle); background: var(--ground); font-size: 14px; color: var(--ink); outline: none;"
              >
                ${uploadPermittedFolders.map(f => `
                  <option value="${f.title}" ${state.selectedFolder === f.title ? "selected" : ""}>
                    ${f.title}${f.title.toLowerCase() === "general" ? " (Default Archive)" : ""}${f.effective_access ? ` · [${f.effective_access}]` : ""}
                  </option>
                `).join("")}
              </select>
            ` : `
              <select 
                id="target-album-select" 
                disabled
                style="width: 100%; padding: 11px 14px; border-radius: 10px; border: 1px solid var(--border-subtle); background: var(--surface-muted); font-size: 13px; color: var(--ink-muted); outline: none; cursor: not-allowed;"
              >
                <option value="" disabled selected>No collections with upload permissions</option>
              </select>
              <p style="font-size: 12px; color: var(--ink-muted); margin-top: 6px;">
                Your account does not have upload authority on any collections in this workspace.
              </p>
            `}
          </div>

          <div>
            <label style="display: block; font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--ink);">
              Processing Pipeline
            </label>
            <label 
              style="
                display: flex; 
                align-items: center; 
                gap: 10px; 
                padding: 10px 14px; 
                border-radius: 10px; 
                border: 1px solid var(--border-subtle); 
                background: var(--surface-muted); 
                cursor: pointer;
                font-size: 13px;
                color: var(--ink);
              "
            >
              <input type="checkbox" id="use-celery-toggle" ${state.useCelery ? "checked" : ""} style="cursor: pointer; accent-color: var(--ink);" />
              <div>
                <span style="font-weight: 600;">Asynchronous Celery Fleet</span>
                <span style="display: block; font-size: 11px; color: var(--ink-muted);">Non-blocking distributed worker processing</span>
              </div>
            </label>
          </div>
        </div>

        <!-- Staged Files Preview Strip -->
        ${state.stagedFiles.length > 0 ? `
          <div style="margin-top: 28px; padding-top: 24px; border-top: 1px solid var(--border-subtle);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
              <div style="font-size: 14px; font-weight: 600; color: var(--ink);">
                Selected Photos: <span class="hl-pill mint" style="font-size: 12px; margin-left: 6px;">${totalValid} photos · ${totalSizeFormatted}</span>
              </div>
              <button type="button" id="clear-all-staged-btn" style="background: none; border: none; font-size: 13px; color: var(--ink-muted); text-decoration: underline; cursor: pointer;">
                Clear all
              </button>
            </div>

            <!-- Scrollable Staged Thumbnails Grid -->
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 14px; max-height: 280px; overflow-y: auto; padding-right: 4px;">
              ${state.stagedFiles.map((item) => `
                <div 
                  style="
                    position: relative; 
                    background: var(--ground); 
                    border: 1px solid ${item.isValid ? "var(--border-subtle)" : "#FECACA"}; 
                    border-radius: 12px; 
                    overflow: hidden; 
                    display: flex; 
                    flex-direction: column;
                  "
                >
                  <div style="width: 100%; height: 95px; background: var(--surface-muted); position: relative; overflow: hidden;">
                    ${item.previewUrl ? `
                      <img src="${item.previewUrl}" alt="${item.name}" style="width: 100%; height: 100%; object-fit: cover;" />
                    ` : `
                      <div style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 24px; color: #DC2626;">
                        <span style="font-size: 16px; font-weight: 700; color: #DC2626;">!</span>
                      </div>
                    `}
                    <button 
                      type="button" 
                      class="remove-staged-file-btn" 
                      data-file-id="${item.id}"
                      aria-label="Remove photo"
                      style="
                        position: absolute; 
                        top: 6px; 
                        right: 6px; 
                        width: 22px; 
                        height: 22px; 
                        border-radius: 50%; 
                        background: rgba(17, 24, 28, 0.7); 
                        color: #FFFFFF; 
                        border: none; 
                        display: flex; 
                        align-items: center; 
                        justify-content: center; 
                        font-size: 11px; 
                        cursor: pointer;
                        backdrop-filter: blur(4px);
                      "
                    >&times;</button>
                  </div>
                  <div style="padding: 8px 10px; font-size: 11px;">
                    <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--ink);" title="${item.name}">
                      ${item.name}
                    </div>
                    <div style="color: ${item.isValid ? "var(--ink-muted)" : "#DC2626"}; font-size: 10px; margin-top: 2px;">
                      ${item.isValid ? item.sizeFormatted : (item.error || "Invalid")}
                    </div>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>
        ` : ""}

        <!-- Action Button -->
        <div style="margin-top: 28px;">
          <button 
            type="button" 
            class="btn-pill-black" 
            id="start-batch-upload-btn" 
            style="width: 100%; justify-content: center; padding: 14px 28px; font-size: 15px;"
            ${totalValid === 0 || state.isUploading || !hasUploadAccess ? "disabled" : ""}
          >
            ${!hasUploadAccess 
              ? "Upload Permission Required" 
              : (state.isUploading ? "Uploading &amp; Extracting Identities..." : `Upload &amp; Index ${totalValid} Photo${totalValid === 1 ? "" : "s"} →`)}
          </button>
        </div>
          </button>
        </div>
      </div>
    </div>
  `;
}

