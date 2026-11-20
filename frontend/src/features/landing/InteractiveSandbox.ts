/**
 * InteractiveSandbox Component
 * Live Try-It Face Search Sandbox for the landing page.
 * Allows users to test clicking faces in a photo and seeing instant matching results.
 */

import { renderHighlighterPill } from "../../components/primitives/HighlighterPill";

export interface InteractiveSandboxProps {
  activePersonName?: string;
}

export function renderInteractiveSandbox(props: InteractiveSandboxProps = {}): string {
  const activePerson = props.activePersonName || "Elena Rostova";

  const matchesForElena = [
    { title: "Keynote Opening Speech", album: "Keynote Presentations", match: "99% Match", img: "https://images.unsplash.com/photo-1511578314322-379afb476865?auto=format&fit=crop&w=400&q=80" },
    { title: "VIP Step & Repeat Portrait", album: "VIP Gala Red Carpet", match: "98% Match", img: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=80" },
    { title: "Leadership Executive Panel", album: "Keynote Presentations", match: "97% Match", img: "https://images.unsplash.com/photo-1522071820081-009f0129c71c?auto=format&fit=crop&w=400&q=80" },
  ];

  const matchesForMarcus = [
    { title: "Main Stage Opening Remarks", album: "VIP Gala Red Carpet", match: "99% Match", img: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=400&q=80" },
    { title: "Outdoor Brainstorming Session", album: "Summer Retreat", match: "98% Match", img: "https://images.unsplash.com/photo-1528605248644-14dd04022da1?auto=format&fit=crop&w=400&q=80" },
    { title: "Panel Discussion Highlights", album: "Keynote Presentations", match: "96% Match", img: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=400&q=80" },
  ];

  const currentMatches = activePerson === "Marcus Chen" ? matchesForMarcus : matchesForElena;

  return `
    <section 
      class="sandbox-section" 
      style="
        background: var(--card); 
        border: 1px solid var(--border-subtle); 
        border-radius: var(--radius-lg); 
        padding: 36px 28px; 
        margin: 56px 0;
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.03);
      "
      aria-label="Interactive visual search demonstration"
    >
      <div style="text-align: center; max-width: 600px; margin: 0 auto 32px auto;">
        <span class="hl-pill mint" style="font-size: 12px; margin-bottom: 12px;">Interactive Sandbox</span>
        <h2 style="font-size: clamp(24px, 3.2vw, 36px); margin-bottom: 10px;">
          Try it live: Click a face to discover them
        </h2>
        <p style="font-size: 15px; color: var(--ink-secondary);">
          Our AI isolates identities automatically. Click either person below to search across the entire event gallery.
        </p>
      </div>

      <!-- Interactive Reference Photo Canvas -->
      <div style="display: grid; grid-template-columns: minmax(300px, 420px) 1fr; gap: 36px; align-items: start;">
        <div style="position: relative; border-radius: 14px; overflow: hidden; background: var(--surface-muted); border: 1px solid var(--border-subtle);">
          <img 
            src="https://images.unsplash.com/photo-1522071820081-009f0129c71c?auto=format&fit=crop&w=800&q=80" 
            alt="Sample Event Group Photo" 
            style="width: 100%; height: 280px; object-fit: cover; display: block;"
          />

          <!-- Clickable Face Target 1: Elena -->
          <button 
            type="button"
            class="sandbox-face-target"
            data-target-person="Elena Rostova"
            style="
              position: absolute;
              top: 24%;
              left: 28%;
              width: 58px;
              height: 58px;
              border-radius: 50%;
              border: 3px solid ${activePerson === "Elena Rostova" ? "var(--ochre)" : "#FFFFFF"};
              background-color: ${activePerson === "Elena Rostova" ? "rgba(217, 119, 6, 0.2)" : "transparent"};
              cursor: pointer;
              transition: transform 0.2s ease, border-color 0.2s ease;
              outline: none;
            "
            aria-label="Search for Elena Rostova"
            title="Click to search for Elena"
          >
            <span style="position: absolute; bottom: -24px; left: 50%; transform: translateX(-50%); background: rgba(17,24,28,0.85); color: #FFF; font-size: 11px; padding: 2px 8px; border-radius: 999px; white-space: nowrap;">
              Elena Rostova
            </span>
          </button>

          <!-- Clickable Face Target 2: Marcus -->
          <button 
            type="button"
            class="sandbox-face-target"
            data-target-person="Marcus Chen"
            style="
              position: absolute;
              top: 28%;
              left: 64%;
              width: 56px;
              height: 56px;
              border-radius: 50%;
              border: 3px solid ${activePerson === "Marcus Chen" ? "var(--ochre)" : "#FFFFFF"};
              background-color: ${activePerson === "Marcus Chen" ? "rgba(217, 119, 6, 0.2)" : "transparent"};
              cursor: pointer;
              transition: transform 0.2s ease, border-color 0.2s ease;
              outline: none;
            "
            aria-label="Search for Marcus Chen"
            title="Click to search for Marcus"
          >
            <span style="position: absolute; bottom: -24px; left: 50%; transform: translateX(-50%); background: rgba(17,24,28,0.85); color: #FFF; font-size: 11px; padding: 2px 8px; border-radius: 999px; white-space: nowrap;">
              Marcus Chen
            </span>
          </button>
        </div>

        <!-- Matching Photos Result Stream -->
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <div style="font-weight: 700; font-size: 16px;">
              Matches for <span class="hl-pill rose" style="font-size: 13px;">${activePerson}</span>
            </div>
            <span style="font-size: 12px; color: var(--ink-muted);">3 sample matches found</span>
          </div>

          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px;">
            ${currentMatches.map(m => `
              <div class="photo-card" style="box-shadow: none;">
                <img src="${m.img}" alt="${m.title}" style="width: 100%; height: 130px; object-fit: cover; display: block;" loading="lazy" />
                <div style="padding: 10px;">
                  <div style="font-weight: 700; font-size: 13px; line-height: 1.3; margin-bottom: 4px;">${m.title}</div>
                  <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--ink-muted);">
                    <span>${m.album}</span>
                    <span class="hl-pill mint" style="padding: 1px 6px; font-size: 10px;">${m.match}</span>
                  </div>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      </div>
    </section>
  `;
}

