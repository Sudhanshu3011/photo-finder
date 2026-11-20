import { renderHighlighterPill } from "../../components/primitives/HighlighterPill.js";
import { renderUnderlineText } from "../../components/primitives/UnderlineText.js";
import { renderButtonPill } from "../../components/primitives/ButtonPill.js";

export function renderHeroConstellation() {
  const headlinePill = renderHighlighterPill({ text: "secured", variant: "rose" });
  const underlineText = renderUnderlineText({ text: "found" });

  const avatars = [
    { src: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=200&q=80", size: 68, alt: "Conference Attendee" },
    { src: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=200&q=80", size: 90, alt: "Keynote Speaker" },
    { src: "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=200&q=80", size: 110, alt: "Event Host" },
    { src: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=200&q=80", size: 80, alt: "Panelist" },
    { src: "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?auto=format&fit=crop&w=200&q=80", size: 96, alt: "VIP Guest" },
    { src: "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?auto=format&fit=crop&w=200&q=80", size: 74, alt: "Creative Director" },
    { src: "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?auto=format&fit=crop&w=200&q=80", size: 86, alt: "Lead Photographer" },
  ];

  return `
    <section class="hero-box" aria-labelledby="hero-heading">
      <!-- Living Atmospheric WebGL Aurora Veil Backdrop (Entire Hero Section till 'Try it live') -->
      <canvas id="hero-aurora-canvas" class="hero-aurora-canvas" aria-hidden="true"></canvas>
      <div class="hero-aurora-overlay" aria-hidden="true"></div>

      <!-- Hero Content Layer -->
      <div class="hero-content-layer">
        <!-- Confident 2-Line Editorial Headline (Velunara Identity) -->
        <h1 id="hero-heading" class="hero-headline">
          Every photo ${headlinePill}. Every face ${underlineText}.
        </h1>

        <p class="hero-subline">
          Velunara gives your organisation a private workspace to store photo archives and search them by face or text. Your data stays isolated, and your team sees only what you allow.
        </p>

        <!-- Floating Constellation Grid from Elementum.jpg -->
        <div class="constellation-wrapper" role="region" aria-label="Constellation of familiar faces">
          ${avatars.map(avatar => `
            <img 
              src="${avatar.src}" 
              class="avatar-circle" 
              style="width: ${avatar.size}px; height: ${avatar.size}px;" 
              alt="${avatar.alt}" 
              loading="lazy"
            />
          `).join("")}
        </div>

        <!-- Action Button -->
        <div style="margin-top: 28px;">
          ${renderButtonPill({
            label: "Get Started →",
            variant: "primary",
            className: "btn-hero-cta",
            ariaLabel: "Get started with Velunara Workspace",
          })}
        </div>
      </div>
    </section>
  `;
}
