/**
 * EditorialZigZag Component
 * Alternating narrative panels with circular photographic crops from Elementum.jpg.
 */

import { renderHighlighterPill } from "../../components/primitives/HighlighterPill";

export function renderEditorialZigZag(): string {
  const mintPillToday = renderHighlighterPill({ text: "today", variant: "mint" });
  const mintPillSee = renderHighlighterPill({ text: "See", variant: "mint" });

  return `
    <section class="zigzag-wrapper" aria-label="Editorial narrative">
      <!-- Panel 1: Text Left, Circular Frame Right -->
      <div class="zigzag-block">
        <div>
          <h2 style="font-size: clamp(28px, 3.8vw, 42px); margin-bottom: 18px; line-height: 1.15;">
            Tomorrow should be better than ${mintPillToday}
          </h2>
          <p style="font-size: 16px; margin-bottom: 24px; max-width: 460px; color: var(--ink-secondary); line-height: 1.6;">
            Every photograph captures a human story. Our platform automatically organizes and identifies recurring people across albums so you never have to manually tag a photo again.
          </p>
          <a class="nav-link" data-tab="people" style="font-weight: 700; color: var(--ink-primary); font-size: 15px; cursor: pointer;">
            Meet your auto-grouped people &rarr;
          </a>
        </div>
        <div class="zigzag-img-frame">
          <img 
            src="https://images.unsplash.com/photo-1511578314322-379afb476865?auto=format&fit=crop&w=800&q=80" 
            alt="Evening gala event attendees" 
            loading="lazy"
          />
        </div>
      </div>

      <!-- Panel 2: Circular Frame Left, Text Right (Inverted) -->
      <div class="zigzag-block reverse">
        <div>
          <h2 style="font-size: clamp(28px, 3.8vw, 42px); margin-bottom: 18px; line-height: 1.15;">
            ${mintPillSee} how we can help you organize
          </h2>
          <p style="font-size: 16px; margin-bottom: 24px; max-width: 460px; color: var(--ink-secondary); line-height: 1.6;">
            Whether searching for an executive's keynote photo or finding candid laughs at a summer retreat, search effortlessly by clicking a face or describing a scene in plain words.
          </p>
          <a class="nav-link" data-tab="search" style="font-weight: 700; color: var(--ink-primary); font-size: 15px; cursor: pointer;">
            Try visual search now &rarr;
          </a>
        </div>
        <div class="zigzag-img-frame">
          <img 
            src="https://images.unsplash.com/photo-1522071820081-009f0129c71c?auto=format&fit=crop&w=800&q=80" 
            alt="Team collaborating around photos" 
            loading="lazy"
          />
        </div>
      </div>
    </section>
  `;
}

