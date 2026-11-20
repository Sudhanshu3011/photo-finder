/**
 * CircularAvatar — Accessible Circular Portrait
 * Provides image loading with alt text, fallback monogram, and accessible touch target bounds.
 */

export interface CircularAvatarProps {
  src: string;
  alt: string;
  size?: number; // diameter in px
  initials?: string;
  backgroundColor?: string;
  title?: string;
  className?: string;
  isInteractive?: boolean;
}

export function renderCircularAvatar(props: CircularAvatarProps): string {
  const {
    src,
    alt,
    size = 48,
    initials = "",
    backgroundColor = "var(--surface-muted)",
    title = "",
    className = "",
    isInteractive = false,
  } = props;

  const minTarget = isInteractive ? Math.max(size, 44) : size;
  const paddingDiff = isInteractive && size < 44 ? (44 - size) / 2 : 0;

  return `
    <div 
      class="avatar-container ${className}" 
      style="display: inline-flex; align-items: center; justify-content: center; min-width: ${minTarget}px; min-height: ${minTarget}px;"
      ${title ? `title="${title}"` : ""}
    >
      ${src ? `
        <img 
          src="${src}" 
          alt="${alt}" 
          class="avatar-circle" 
          style="width: ${size}px; height: ${size}px;"
          loading="lazy"
        />
      ` : `
        <div 
          class="avatar-circle avatar-fallback" 
          style="width: ${size}px; height: ${size}px; background-color: ${backgroundColor}; display: flex; align-items: center; justify-content: center; font-weight: 700; color: var(--ink-primary);"
          aria-label="${alt}"
        >
          ${initials}
        </div>
      `}
    </div>
  `;
}

