# VisualSearch UI/UX Design Specification & Google Stitch Prompt Guide
**Document Version:** 2.0.0 (User-Centric & Human-Friendly Edition)  
**Design System Codename:** *Elementum Editorial*  
**Aesthetic Heritage:** Editorial Typography, Organic Circular Constellations, Pastel Highlighter Accents (`Elementum.jpg`), Anti-Slop Discipline (`design-taste-frontend`).  
**Core Philosophy:** The user never needs to know the algorithms, background queues, or model names. The UI must warmly acknowledge the user, celebrate their photos and people, and make visual discovery natural and effortless.

---

## 1. User-Centric Philosophy & Anti-Slop Principles

### 1.1 Speaking the User's Language (Zero Technical Jargon)
The people using this application are photographers, event coordinators, creative directors, and team members. They care about their memories, their clients, and finding the right photo in seconds.

| Internal Tech / Engineering Term | Banned From UI | User-Facing Human Language |
| :--- | :--- | :--- |
| `RetinaFace / ArcFace Biometrics` | [ ] Banned | **"Find by Face" / "People You Know"** |
| `CLIP Semantic Vectors` | [ ] Banned | **"Search by Scene or Mood"** |
| `HDBSCAN Unsupervised Clustering` | [ ] Banned | **"Auto-Grouped People" / "Identified Faces"** |
| `FAISS Vector Index / Angular Cosine` | [ ] Banned | **"Search Matches" / "Match Accuracy (High / Exact)"** |
| `Celery Worker Fleet / S3 Queues` | [ ] Banned | **"Organizing Your Photos" / "Upload & Discovery Progress"** |
| `Two-Tier Hybrid Folder ACL` | [ ] Banned | **"Album Sharing & Permissions"** |
| `can_read, can_upload, can_manage` | [ ] Banned | **"Can view", "Can add photos", "Full access"** |
| `Tenant ID / Org UUID` | [ ] Banned | **"Workspace Name" (e.g. *Acme Photography Studio*)** |

### 1.2 Acknowledging the User & Creating Delight
1. **Personalized Context:** Always greet and orient the user: *"Good afternoon, Elena · Studio Alpha Workspace"*.
2. **Clear Feedback Loops:** When photos are uploaded, report meaningful outcomes, not background tasks: *"We found 18 new photos of Marcus and 4 group shots"*.
3. **Frictionless Onboarding:** If an invited user logs in, show a warm welcome card: *"You've been invited to join Metropolis Events with photo contributor access"*.

### 1.3 Anti-Slop Rules (`design-taste-frontend`)
- **No Assistant Palettes:** Strictly zero purple, neon blue, or violet gradients.
- **No Meaningless Icon Tiles:** No cards with icons in tinted circles or empty vanity charts.
- **Honest Whitespace & Tone Steps:** Content separation is achieved through subtle tone shifts and generous spacing, not heavy drop shadows.
- **Two-Line Headline Ceiling:** Every headline is punchy, confident, and fits within two lines at every screen width.

---

## 2. Design System Tokens & Foundations (Derived from `Elementum.jpg`)

### 2.1 Color Palette
The aesthetic mirrors high-end editorial magazines: warm, tactile, and human.

| Token Name | Hex Code | Visual Role |
| :--- | :--- | :--- |
| `--surface-ground` | `#FAFAF7` | Warm gallery canvas (soft ivory, easy on the eyes) |
| `--surface-card` | `#FFFFFF` | Elevated card planes and modal sheets |
| `--surface-muted` | `#F2F2EC` | Subtle tone step for table headers and neutral pills |
| `--surface-mint` | `#D9EFE6` | The signature Elementum footer field and highlight accent |
| `--ink-primary` | `#11181C` | High-contrast editorial ink for titles and primary text |
| `--ink-secondary` | `#4A5568` | Friendly descriptive text and photo metadata |
| `--ink-muted` | `#718096` | Timestamps, photo counts, and subtle helper notes |
| `--accent-ochre` | `#D97706` | Hand-drawn marker underlines and warm accent touches |
| `--pill-mint` | `#D8F3DC` | Soft green highlighter capsule behind key words |
| `--pill-rose` | `#FCE7F3` | Soft blush highlighter capsule for person names & tags |
| `--pill-butter` | `#FEF3C7` | Soft butter highlighter capsule for alerts and filters |
| `--action-black` | `#0A0A0A` | Solid black pill action buttons (text: `#FFFFFF`) |
| `--border-subtle` | `#E4E4DC` | Quiet 1px borders used sparingly on inputs and dividers |

### 2.2 Typography
- **Editorial Headings:** *Cabinet Grotesk* or *Syne* (Bold 700 / ExtraBold 800, tight tracking `-0.03em`, leading `0.95–1.05`).
- **Body & Controls:** *Plus Jakarta Sans* or *General Sans* (Regular 400, Medium 500, SemiBold 600, leading `1.5`).

### 2.3 Signature Elementum Visual Motifs
1. **Highlight Pill Wraps (`.hl-pill`):** Soft pastel rounded capsules (`#D8F3DC` mint, `#FCE7F3` rose) enclosing focal words in headlines.
2. **Ochre Marker Underline (`.hl-underline`):** Tactile, organic hand-drawn stroke positioned beneath action words.
3. **Circular Portrait Constellations:** Borderless circular portraits of varying diameters (56px to 110px) scattered organically around headlines and hero sections.
4. **Three-Part Editorial Index Rows:** Left category/context (15%), Center bold headline (70%), Right slim directional arrow `→` (15%).
5. **Solid Pill Action Buttons:** Fully rounded black buttons (`border-radius: 999px`) that convey confidence and tactile feedback.

---

## 3. User Flows & Screen Architecture

```mermaid
flowchart TD
    A[Public Welcome & Live Search Demo] --> B[Workspace Sign In]
    B -->|Multiple Studios| C[Choose Your Workspace]
    B -->|Single Studio| D[VisualSearch Home Dashboard]
    C --> D
    
    D --> E[Search by Face & Scene]
    D --> F[People & Faces Directory]
    D --> G[Add & Organize Photos (Batch Intake)]
    D --> H[Albums & Shared Access]
    D --> I[Studio Team & Settings]
```

---

## 4. Screen-by-Screen Blueprints & Google Stitch Prompts

### Screen 1: Public Welcome & Live Search Playground
**Goal:** Introduce the app with high editorial taste, showing users they can find anyone or any moment in their photo library instantly.

#### Layout Blueprint
- **Header:** Minimal bar. Left: `VisualSearch` wordmark. Center: `Explore`, `People`, `Albums`, `About`. Right: `Open Workspace` solid black pill button.
- **Hero:**
  - Headline (2 lines): *"Find every face and <span class="hl-pill mint">treasured moment</span> with <span class="hl-underline">effortless ease</span>."*
  - Friendly Subline: *"Private visual intelligence for studios and creative teams. Organize millions of event photos and discover who's in them instantly."*
  - **Portrait Constellation:** 7 floating circular photos of happy people, attendees, and speakers at events, arranged organically with generous spacing.
- **Interactive Try-It Sandbox:**
  - Friendly drag-and-drop box: *"Try it yourself: drop any portrait or event photo"*.
  - When a photo is dropped: draws clean circular focus tags over faces found with a prompt: *"Click a face to find other photos of this person"*.
  - Shows 4 matching photo cards below with a clear tag: `Found in 14 photos`.
- **Three-Part Feature Index:**
  - Row 1: `Instant Discovery` | `Find anyone just by clicking their face` | `→`
  - Row 2: `Automatic Organization` | `Photos auto-group into individual people galleries` | `→`
  - Row 3: `Private & Secure` | `Complete control over who can view or add photos` | `→`
- **Pastel Mint Closing Block:** Full-width `#D9EFE6` field with a friendly headline *"Ready to experience effortless photo search?"* and a solid black pill button *"Start Free Trial"*.

```markdown
<!-- GOOGLE STITCH PROMPT: SCREEN 1 -->
Prompt: Design a welcoming, editorial web landing page for "VisualSearch", a user-friendly photo search and people discovery platform. The aesthetic is inspired by Elementum.jpg. 

Ground: Warm gallery off-white (#FAFAF7), deep charcoal text (#11181C), with soft pastel mint (#D8F3DC) highlighter capsules behind key words and warm ochre (#D97706) pencil underlines.

Header: Minimalist navbar with bold rounded wordmark "VisualSearch", clean links (Explore, People, Albums), and a solid black pill button "Open Workspace".

Hero: A confident, warm headline: "Find every face and treasured moment with effortless ease." "treasured moment" is wrapped in a pastel mint capsule pill, and "effortless ease" has an ochre marker underline. Around the headline floats an organic constellation of 7 borderless circular portrait photos of diverse people with genuine smiles.

Interactive Sandbox: A clean card titled "See the magic in action". Users can drag a sample photo. The sample shows a group photo with subtle round focus rings on 2 people. Clicking a person reveals a row of 4 photos where that exact person appears, with a friendly badge "14 photos found".

Editorial Feature Rows: Three minimalist rows where each row has small metadata on the left ("Instant Discovery"), a large headline in the center ("Find anyone just by clicking their face"), and a slim arrow on the right.

Footer Block: A calm mint green section (#D9EFE6) with the title "Ready to experience effortless photo search?" and a solid black pill button "Get Started".
```

---

### Screen 2: Choose Your Workspace (Multi-Tenant Selector)
**Goal:** Acknowledge the user by name and make it effortless to enter their intended organization or accept a new team invitation.

#### Layout Blueprint
- **Welcome Header:** *"Welcome back, Elena. Select your workspace."*
- **Workspace Cards:**
  - Card 1: `Studio Alpha Photography` · `Owner` · `14,200 photos` · Monogram avatar in pastel mint.
  - Card 2: `Metropolis Annual Gala 2026` · `Contributor` · `3,400 photos` · Monogram avatar in pastel rose.
- **Pending Invite Alert:** Soft butter pill notification: *"You have an invitation from Apex Media to contribute photos. Accept Invitation →"*.
- **Action:** Minimal link: `+ Create a new studio workspace`.

```markdown
<!-- GOOGLE STITCH PROMPT: SCREEN 2 -->
Prompt: Design a friendly, uncluttered workspace selection screen for VisualSearch in the Elementum Editorial style. 

Background: Warm ivory (#FAFAF7). 
Center sheet: 480px width, flat surface with a subtle 1px border (#E4E4DC). 
Top greeting: "Welcome back, Elena · Select your workspace", with "workspace" highlighted in a soft mint pill (#D8F3DC). 

A vertical list of 2 studio workspaces:
1. "Studio Alpha Photography" with a round mint avatar "SA", subtitle "14,200 photos organized", and a black role pill "Studio Owner".
2. "Metropolis Gala 2026" with a round rose avatar "MG", subtitle "3,400 photos organized", and a gray role pill "Contributor".

Include a warm yellow pill alert at the top: "You're invited to join Apex Media as a photo contributor. Accept →". Footer has a subtle button "+ Create new workspace".
```

---

### Screen 3: The Search Studio (Find by Face or Describe a Moment)
**Goal:** Empower users to search their private photo library without seeing math, vectors, or model names.

#### Layout Blueprint
- **Top Greeting & Studio Context:** *"Studio Alpha Photography / Visual Search"* with Elena's avatar top right.
- **Search Modes Switcher:** Two simple pill tabs:
  - `Find by Face` (Selected)
  - `Search by Scene or Mood`
- **Find by Face Workbench:**
  - **Left Panel (Upload or Select Reference):**
    - Drag-and-drop portrait box: *"Drop a photo of the person you're looking for, or choose from your People gallery below"*.
    - Visual Face Selector: Shows the photo with a clear, friendly circle on the detected face: *"Searching for this person"*.
    - Album Scope Filter: Clean dropdown: *"Search in: All Albums"* or pick specific albums (*"Summer Gala"*, *"Awards Night"*).
    - Match Sensitivity: Simple intuitive pill slider: `Broad Matches` | `Balanced` | `Exact Only`.
    - Button: Solid black pill *"Search Photos"*.
  - **Right Panel (Results):**
    - Friendly Status: *"We found 38 photos of this person across 2 albums"*.
    - Masonry grid of beautiful event photos. Clicking any photo opens an inspection modal with options to download high-res or view the full album.

```markdown
<!-- GOOGLE STITCH PROMPT: SCREEN 3 -->
Prompt: Design a clean, human-centered photo search studio screen in the Elementum style. 

Header: Shows active workspace "Studio Alpha Photography" and tabs "Find by Face" and "Search by Scene".

Left Panel (380px):
A welcoming photo drop area holding an uploaded portrait of a smiling woman. A soft ochre focus circle surrounds her face with the label "Searching for this person". 
Below are two simple controls: an album selector ("All Event Albums") and a sensitivity selector with three pills ("Broad", "Balanced (Recommended)", "Exact Only"). A solid black pill button reads "Find Photos".

Right Panel (Photo Results):
A clear headline: "Found 38 photos in Summer Gala & VIP Reception". 
A beautiful masonry grid of event photos featuring this woman in various scenes (speaking on stage, chatting with guests, candid laughing shots). Each photo has a clean white margin and a small pill on hover showing the album name and date. Completely free of technical jargon, vector scores, or code snippets.
```

---

### Screen 4: People & Faces Directory (Auto-Grouped People)
**Goal:** Give users an automatic, beautifully curated address book of recurring people in their photo library.

#### Layout Blueprint
- **Header:**
  - Title: *"People & <span class="hl-pill rose">Familiar Faces</span>"* (soft blush highlight).
  - Subline: *"We automatically group photos by person so you can browse anyone's gallery in one click."*
  - Search input: *"Search by name..."* and a button *"Refresh People"*.
- **People Gallery Grid:**
  - 4-column responsive grid of clean person cards:
    - **Hero Portrait:** Large circular portrait (96px) showing the clearest photo of the person.
    - **Editable Name:** *"Marcus Chen"* (or *"Add a name"* if unnamed).
    - **Photo Count Pill:** *"148 photos across 4 albums"*.
    - **Sample Angle Previews:** 3 tiny overlapping circular crops showing candid moments.
    - **Quick Action:** *"View all photos →"*.

```markdown
<!-- GOOGLE STITCH PROMPT: SCREEN 4 -->
Prompt: Design a friendly "People & Faces" directory screen for a photo management application in the Elementum Editorial style. 

Background: Warm ivory (#FAFAF7). 
Header: 36px bold heading: "People & Familiar Faces" with "Familiar Faces" enclosed in a soft blush highlighter pill (#FCE7F3). Subtitle: "We automatically group photos by person so you can find anyone in one click."

Grid: A responsive 4-column layout of person cards. 
Each card has a pure white surface with a subtle 1px border (#E4E4DC) and generous 24px padding. 
In the center is a crisp circular portrait (90px diameter) of a person. 
Below it is a clean text field for their name ("David Miller", "Elena Rostova", "Click to name person #14"). 
Under the name is a friendly tag: "64 photos in 3 albums". 
At the bottom are 3 tiny circular thumbnail previews of candid shots, and a slim text link "Browse photos →".
```

---

### Screen 5: Add & Organize Photos (Friendly Batch Intake)
**Goal:** Allow users to upload up to 50 photos with reassuring, clear progress and zero confusing worker or queue terminology.

#### Layout Blueprint
- **Header:** *"Add Photos to <span class="hl-pill butter">Your Albums</span>"*
- **Batch Dropzone:**
  - Large drag-and-drop canvas with a warm dashed border and an icon of stacked photos.
  - Headline: *"Drag up to 50 photos here, or click to browse"*.
  - Helper note: *"Supports high-resolution JPEG, PNG, and RAW. We'll automatically identify people and make every photo searchable."*
- **Album Assignment:**
  - Dropdown: *"Select album: Keynote Presentations"* or `+ Create new album`.
- **Live Progress & Acknowledgment:**
  - Progress headline: *"Organizing your photos... 24 of 50 photos ready"*.
  - Solid charcoal progress bar with smooth fill animation.
  - Friendly Photo Stream: Row of uploaded photo thumbnails showing friendly checkmarks:
    - Thumbnail 1: *"Photo ready · 2 people found"* 
    - Thumbnail 2: *"Photo ready · 1 person found"* 
    - Thumbnail 3: *"Optimizing image..."* 
  - Completion Card: *"All photos organized! 18 people identified. Ready to search."* with a black pill button *"View Album"*.

```markdown
<!-- GOOGLE STITCH PROMPT: SCREEN 5 -->
Prompt: Design an intuitive batch photo upload and organizing screen in the Elementum Editorial aesthetic. 

Top section: An inviting drag-and-drop zone with a soft border and a friendly message: "Drag up to 50 photos here to organize them instantly". It shows an album selector dropdown set to "Annual Summit 2026".

Progress state: 
A reassuring status line: "Organizing your photos... 32 of 50 completed". 
A sleek progress bar filled with solid charcoal (#11181C) over a pale mint ground (#D9EFE6). 
Below is a live preview list of uploaded photos:
Each item shows a 48px square thumbnail of the photo, the filename ("Opening_Keynote_01.jpg"), and a friendly status pill in soft mint: "Ready · 3 people recognized" with a green checkmark. 
Zero mentions of Celery, S3, inference queues, or backend workers.
Bottom right has a solid black pill button "Done & View Album".
```

---

### Screen 6: Albums & Sharing Permissions (Human-Friendly Access)
**Goal:** Manage album privacy and team member permissions with plain, understandable language.

#### Layout Blueprint
- **Album Header:** *"Album Access: <span class="hl-pill mint">VIP Gala Red Carpet</span>"*
- **Permission Matrix Table:**
  - Clean rows for each team member:
    - Member Avatar & Name (`Devon Lane`, `devon@studio.com`)
    - Role Badge (`Studio Admin`)
    - Plain Language Options:
      * **Can View & Search** (Can browse photos and search by face)
      * **Can Add Photos** (Can upload new batches into this album)
      * **Full Album Access** (Can rename, download originals, and invite others)
- **Footer Actions:** Plain text *"Cancel"* and solid black pill button *"Save Permissions"*.

```markdown
<!-- GOOGLE STITCH PROMPT: SCREEN 6 -->
Prompt: Design a clean Album Sharing & Permissions modal in the Elementum style. 

The modal opens over an ivory background. 
Headline: "Sharing & Access: VIP Gala 2026", with "VIP Gala 2026" highlighted in a soft mint pill (#D8F3DC). 

The table lists 3 team members with their circular avatars and email addresses:
Each row has clear, non-technical checkboxes:
1. "Can view & search photos"
2. "Can add photos"
3. "Full album management"

Member 1 (Devon, Photographer): has all 3 options selected.
Member 2 (Sarah, PR Coordinator): has "Can view" and "Can add" selected.
Member 3 (Guest Client): has only "Can view" selected.

The design is warm, spacious, and completely avoids technical permission codes like can_read, ACL, or tenant IDs. Solid black pill button "Update Permissions".
```

---

## 5. Summary & Hand-off for Frontend Development

This revised specification ensures:
1. **The User Feels Acknowledged:** Every screen greets, guides, and reassures the user.
2. **Zero Engineering Jargon:** All machine learning, vector math, and queue infrastructure are tucked behind human-friendly abstractions.
3. **Elementum Soul Preserved:** Warm ivory canvas, pastel highlighter pills, hand-drawn ochre underlines, circular portrait constellations, and solid black pill buttons.
