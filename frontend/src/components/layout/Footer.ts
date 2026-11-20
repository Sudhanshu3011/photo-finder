/**
 * Footer Layout Component
 * Renders the signature Elementum mint field (#D9EFE6) with newsletter and directory.
 */

import { renderButtonPill } from "../primitives/ButtonPill";

export function renderFooter(): string {
  return `
    <footer class="elementum-footer" role="contentinfo" aria-label="Site Footer">
      <div class="footer-inner">
        <!-- Newsletter Header -->
        <h3 class="footer-title">
          Subscribe to our newsletter
        </h3>
        <p style="margin-bottom: 28px; color: var(--ink-secondary); font-size: 16px;">
          To make your stay special and even more memorable
        </p>

        <!-- Newsletter Action Form -->
        <form 
          onsubmit="event.preventDefault(); alert('Thank you for subscribing to Velunara updates!');"
          style="display: flex; justify-content: center; align-items: center; gap: 12px; max-width: 460px; margin: 0 auto 36px auto; flex-wrap: wrap;"
        >
          <label for="newsletter-email" class="sr-only" style="position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); border: 0;">
            Email address
          </label>
          <input 
            type="email" 
            id="newsletter-email" 
            placeholder="Enter your email address..." 
            required
            style="
              flex: 1;
              min-width: 240px;
              min-height: 44px;
              padding: 10px 18px;
              border-radius: var(--radius-pill);
              border: 1px solid #B8DACB;
              background-color: #FFFFFF;
              font-family: var(--font-body);
              font-size: 14px;
              color: var(--ink-primary);
              outline: none;
            "
          />
          ${renderButtonPill({
            label: "Subscribe Now",
            type: "submit",
            variant: "primary",
            ariaLabel: "Subscribe to newsletter",
          })}
        </form>

        <!-- Directory Links Grid -->
        <div class="footer-links-grid">
          <div class="footer-col">
            <h5>Company</h5>
            <ul>
              <li><a href="#home" class="nav-link" data-tab="home" style="padding: 0; font-size: 14px;">Home</a></li>
              <li><a href="#studio" class="nav-link" data-tab="search" style="padding: 0; font-size: 14px;">Studio</a></li>
              <li><a href="#service" class="nav-link" data-tab="people" style="padding: 0; font-size: 14px;">Service</a></li>
              <li><a href="#blog" class="nav-link" data-tab="upload" style="padding: 0; font-size: 14px;">Upload</a></li>
            </ul>
          </div>

          <div class="footer-col">
            <h5>Terms &amp; Policies</h5>
            <ul>
              <li><a href="#privacy" style="color: inherit; text-decoration: none;">Privacy Policy</a></li>
              <li><a href="#terms" style="color: inherit; text-decoration: none;">Terms &amp; Conditions</a></li>
              <li><a href="#explore" style="color: inherit; text-decoration: none;">Explore</a></li>
              <li><a href="#accessibility" style="color: inherit; text-decoration: none;">Accessibility</a></li>
            </ul>
          </div>

          <div class="footer-col">
            <h5>Follow Us</h5>
            <ul>
              <li><a href="#instagram" style="color: inherit; text-decoration: none;">Instagram</a></li>
              <li><a href="#linkedin" style="color: inherit; text-decoration: none;">LinkedIn</a></li>
              <li><a href="#youtube" style="color: inherit; text-decoration: none;">YouTube</a></li>
              <li><a href="#twitter" style="color: inherit; text-decoration: none;">Twitter</a></li>
            </ul>
          </div>

          <div class="footer-col">
            <h5>Studio Location</h5>
            <ul>
              <li>1498w Fulton St, STE 2D</li>
              <li>Chicago, IL 63867</li>
              <li>(123) 456-7890</li>
              <li>info@velunara.com</li>
            </ul>
          </div>
        </div>

        <div style="font-size: 13px; color: var(--ink-muted); margin-top: 48px; border-top: 1px solid rgba(0,0,0,0.06); padding-top: 24px;">
          &copy; 2026 Velunara Workspace. Built with Elementum Editorial Craft. All rights reserved.
        </div>
      </div>
    </footer>
  `;
}

