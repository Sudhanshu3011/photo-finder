import { renderHighlighterPill } from "../../components/primitives/HighlighterPill.js";

export function renderCapabilityIndex() {
  const mintPillCan = renderHighlighterPill({ text: "can", variant: "mint" });

  const rows = [
    {
      tab: "search",
      num: "01",
      title: "Instant Search",
      desc: "Find any person, moment or keyword across your organisation’s photo collections in seconds. Your whole team searches in one place.",
      ariaLabel: "Go to Search",
    },
    {
      tab: "people",
      num: "02",
      title: "Smart Face Grouping",
      desc: "Velunara recognises recurring faces and automatically builds a gallery for each person. No manual tagging, no sorting by hand.",
      ariaLabel: "Go to People",
    },
    {
      tab: "upload",
      num: "03",
      title: "Fast Photo Upload",
      desc: "Add photos to your workspace in a few clicks. They are organised and ready to search as soon as they arrive.",
      ariaLabel: "Go to Upload",
    },
    {
      tab: "albums",
      num: "04",
      title: "Role-Based Privacy",
      desc: "Control who sees what. Give admins, team members and guests the right level of access, and keep each workspace fully isolated.",
      ariaLabel: "Go to Collections",
    },
  ];

  return `
    <section class="capability-index-section" style="margin: 80px 0 40px 0;" aria-labelledby="capabilities-heading">
      <h2 id="capabilities-heading" style="font-size: clamp(28px, 3.8vw, 40px); margin-bottom: 32px;">
        What we ${mintPillCan} offer you
      </h2>

      <div class="editorial-rows-container" role="list">
        ${rows.map(row => `
          <div 
            class="editorial-row" 
            data-tab="${row.tab}"
            role="listitem"
            tabindex="0"
            aria-label="${row.ariaLabel}: ${row.title}"
            style="padding: 26px 12px;"
          >
            <div class="row-meta" style="font-size: 15px; font-weight: 700; color: var(--ink-secondary);">${row.num}</div>
            <div class="row-title">
              <div style="font-size: 21px; font-weight: 700; color: var(--ink); margin-bottom: 6px;">${row.title}</div>
              <p style="font-size: 15px; color: var(--ink-secondary); margin: 0; line-height: 1.55;">${row.desc}</p>
            </div>
            <div class="row-arrow" aria-hidden="true">&rarr;</div>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}
