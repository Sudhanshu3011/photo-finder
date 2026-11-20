/**
 * ProgressMonitor Feature Component
 * Real-time progress bar, friendly human outcome stream items,
 * and completion celebration card.
 * Adheres strictly to design-taste-frontend, Elementum aesthetic, and anti-slop rules.
 */

export interface ProcessedPhotoItem {
  id: string;
  filename: string;
  thumbUrl: string;
  status: "pending" | "processing" | "ready" | "error";
  facesCount?: number;
  peopleNames?: string[];
  message?: string;
}

export interface ProgressMonitorProps {
  progress: number;
  stage: string;
  jobId?: string | null;
  items: ProcessedPhotoItem[];
  isComplete: boolean;
  folderName: string;
  totalPhotos: number;
  peopleRecognizedCount: number;
  onSearchClick?: () => void;
  onPeopleClick?: () => void;
  onResetClick?: () => void;
}

export function renderProgressMonitor(props: ProgressMonitorProps): string {
  const percent = Math.min(100, Math.max(0, Math.round(props.progress)));

  if (props.isComplete) {
    return renderUploadSuccessCard(props);
  }

  return `
    <div 
      id="upload-progress-card" 
      style="
        background: var(--card); 
        border: 1px solid var(--border-subtle); 
        border-radius: var(--radius-lg); 
        padding: 32px; 
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.03);
        margin-top: 24px;
      "
    >
      <!-- Progress Bar Header -->
      <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px;">
        <div>
          <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 4px; color: var(--ink);">
            Organizing your photos...
          </h3>
          <p id="upload-progress-stage-text" style="font-size: 13px; color: var(--ink-secondary);">
            ${props.stage || "Securing photos and extracting facial signatures..."}
          </p>
        </div>
        <div id="upload-progress-percent-label" style="font-size: 16px; font-weight: 700; color: var(--ink); font-family: monospace;">
          ${percent}%
        </div>
      </div>

      <!-- Linear Charcoal on Mint Progress Track -->
      <div 
        style="
          width: 100%; 
          height: 10px; 
          background: #D9EFE6; 
          border-radius: 999px; 
          overflow: hidden; 
          position: relative; 
          margin-bottom: 24px;
        "
      >
        <div 
          id="upload-progress-fill-bar"
          style="
            width: ${percent}%; 
            height: 100%; 
            background: #11181C; 
            border-radius: 999px; 
            transition: width 0.3s cubic-bezier(0.16, 1, 0.3, 1);
          "
        ></div>
      </div>

      <!-- Friendly Processing Stream Items -->
      <div style="margin-top: 16px;">
        <div id="upload-progress-counter-text" style="font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-muted); margin-bottom: 12px;">
          Live Organization Stream (${props.items.filter(i => i.status === "ready").length} / ${props.totalPhotos || props.items.length} indexed)
        </div>

        <div style="display: flex; flex-direction: column; gap: 10px; max-height: 320px; overflow-y: auto; padding-right: 4px;">
          ${props.items.map((item) => `
            <div 
              class="upload-stream-item" 
              style="
                display: flex; 
                align-items: center; 
                gap: 14px; 
                padding: 10px 14px; 
                background: var(--surface-muted); 
                border-radius: 10px; 
                border: 1px solid var(--border-subtle);
              "
            >
              <!-- Thumbnail -->
              <div style="width: 44px; height: 44px; border-radius: 8px; overflow: hidden; background: var(--ground); flex-shrink: 0;">
                ${item.thumbUrl ? `
                  <img src="${item.thumbUrl}" alt="Thumbnail" style="width: 100%; height: 100%; object-fit: cover;" />
                ` : `
                  <div style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 12px; color: #94A3B8;">Preview</div>
                `}
              </div>

              <!-- File Info & Friendly Outcome -->
              <div style="flex: 1; min-width: 0;">
                <div style="font-weight: 600; font-size: 13px; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                  ${item.filename}
                </div>
                <div style="font-size: 12px; color: var(--ink-secondary); margin-top: 2px;">
                  ${item.status === "ready" 
                    ? (item.facesCount && item.facesCount > 0 
                        ? `Photo ready · ${item.facesCount} ${item.facesCount === 1 ? "person" : "people"} recognized ${item.peopleNames && item.peopleNames.length > 0 ? `(${item.peopleNames.join(", ")})` : ""}`
                        : "Photo ready · Visual scene indexed")
                    : (item.status === "processing" 
                        ? "Extracting facial features & vectors..." 
                        : "Queued for pipeline")}
                </div>
              </div>

              <!-- Status Pill Badge -->
              <div>
                ${item.status === "ready" ? `
                  <span class="hl-pill mint" style="font-size: 11px; font-weight: 600; padding: 4px 10px;">Ready</span>
                ` : item.status === "processing" ? `
                  <span class="hl-pill rose" style="font-size: 11px; font-weight: 600; padding: 4px 10px;">Indexing...</span>
                ` : `
                  <span style="font-size: 11px; color: var(--ink-muted); padding: 4px 8px;">Queued</span>
                `}
              </div>
            </div>
          `).join("")}
        </div>
      </div>
    </div>
  `;
}

export function renderUploadSuccessCard(props: ProgressMonitorProps): string {
  return `
    <div 
      id="upload-success-card" 
      style="
        background: var(--card); 
        border: 1px solid var(--border-subtle); 
        border-radius: var(--radius-lg); 
        padding: 36px 32px; 
        box-shadow: 0 6px 30px rgba(0, 0, 0, 0.04);
        margin-top: 24px;
        text-align: center;
      "
    >
      <div 
        style="
          width: 64px; 
          height: 64px; 
          margin: 0 auto 18px auto; 
          background: #D9EFE6; 
          border-radius: 50%; 
          display: flex; 
          align-items: center; 
          justify-content: center; 
          font-size: 28px; 
          color: #064E3B;
        "
      >
        [OK]
      </div>

      <span class="hl-pill mint" style="font-size: 12px; margin-bottom: 12px; display: inline-block;">Batch Ingestion Complete</span>
      <h2 style="font-size: 26px; font-weight: 700; margin-bottom: 8px; color: var(--ink);">
        All Photos Secured &amp; Organized
      </h2>
      <p style="font-size: 15px; color: var(--ink-secondary); max-width: 540px; margin: 0 auto 28px auto; line-height: 1.6;">
        ${props.totalPhotos} photos have been indexed into the <strong>${props.folderName || "General Archive"}</strong> collection. 
        ${props.peopleRecognizedCount > 0 ? `${props.peopleRecognizedCount} unique recurring faces have been grouped into your People directory.` : "Visual similarity vectors are now ready for search."}
      </p>

      <!-- Action Navigation Buttons -->
      <div style="display: flex; gap: 14px; justify-content: center; flex-wrap: wrap;">
        <button 
          type="button" 
          class="btn-pill-black" 
          id="success-search-btn" 
          style="padding: 12px 24px; font-size: 14px;"
        >
          Search in Visual Search →
        </button>
        <button 
          type="button" 
          class="btn-secondary" 
          id="success-people-btn" 
          style="padding: 12px 24px; font-size: 14px;"
        >
          View People &amp; Faces
        </button>
        <button 
          type="button" 
          class="btn-secondary" 
          id="success-reset-btn" 
          style="padding: 12px 20px; font-size: 14px; background: transparent;"
        >
          + Upload Another Batch
        </button>
      </div>
    </div>
  `;
}

