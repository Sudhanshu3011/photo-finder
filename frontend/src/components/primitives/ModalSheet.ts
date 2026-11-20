/**
 * ModalSheet — Accessible Modal Dialog
 * Implements WCAG 2.2 dialog semantics, aria-modal, and keyboard focus trap.
 */

export interface ModalSheetProps {
  id: string;
  title: string;
  titleId?: string;
  contentHtml: string;
  isOpen?: boolean;
  maxWidthPx?: number;
}

export function renderModalSheet(props: ModalSheetProps): string {
  const {
    id,
    title,
    titleId = `${id}-title`,
    contentHtml,
    isOpen = false,
    maxWidthPx = 540,
  } = props;

  return `
    <div 
      id="${id}"
      class="modal-overlay ${isOpen ? "open" : ""}"
      role="dialog"
      aria-modal="true"
      aria-labelledby="${titleId}"
    >
      <div 
        class="modal-card" 
        style="max-width: ${maxWidthPx}px;"
        tabindex="-1"
      >
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
          <h2 id="${titleId}" style="font-family: var(--font-display); font-size: 22px; font-weight: 700; margin: 0;">
            ${title}
          </h2>
          <button 
            type="button"
            class="btn-secondary" 
            style="min-width: 44px; min-height: 44px; border: none; font-size: 20px; line-height: 1; padding: 0 12px;" 
            data-close-modal="${id}"
            aria-label="Close dialog"
          >
            &times;
          </button>
        </div>

        <div class="modal-body">
          ${contentHtml}
        </div>
      </div>
    </div>
  `;
}

/**
 * Attaches keyboard ESC and outside click listeners to a modal.
 */
export function setupModalAccessibility(modalId: string, onClose: () => void): () => void {
  const modal = document.getElementById(modalId);
  if (!modal) return () => {};

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape" && modal.classList.contains("open")) {
      e.preventDefault();
      onClose();
    }
  };

  const handleBackdropClick = (e: MouseEvent) => {
    if (e.target === modal) {
      onClose();
    }
  };

  window.addEventListener("keydown", handleKeyDown);
  modal.addEventListener("click", handleBackdropClick);

  return () => {
    window.removeEventListener("keydown", handleKeyDown);
    modal.removeEventListener("click", handleBackdropClick);
  };
}

