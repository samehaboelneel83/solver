# MCAIT Design System

The shared design language for **MCAIT** — a suite of products under one company, in the spirit of Google Workspace, Apple, or Huawei's app ecosystem. One agentic chatbot at the center (**Cowork**), surrounded by a family of productivity products (Drive, Calendar, Meet, Notebook, Mail).

This repository is the single source of truth for the brand's typography, color, spacing, iconography, reusable UI components, and full-screen product recreations.

---

## Company & product context

MCAIT builds a **secure, self-hostable productivity platform**. The flagship is an agentic AI hub; the rest of the suite mirrors the apps people already know (storage, calendar, video, research notebooks, mail), all sharing one account, one shell, and one design language.

| Product | Role | Accent hue |
|---|---|---|
| **Cowork** | Agentic chatbot hub (Gemini-like) — the flagship | **Gold** (wears the brand) |
| **Drive** | File storage & sharing | Blue |
| **Calendar** | Scheduling | Green |
| **Meet** | Video conferencing | Teal / cyan |
| **Notebook** | Research notebooks (NotebookLM-like) | Violet |
| **Mail** | Communications | Coral / red |
| **Aura Translate** | AI-powered translation | Rose / pink |

### Design strategy — two-tier color
The cohesion trick used by every great product suite (Google, Apple, Microsoft):
1. **Gold is the constant brand signature.** It owns the logo/seal, the platform shell, the Cowork hub, and platform-level primary moments. It stays *rare and premium* — not the color of every button.
2. **Cool-slate neutrals are universal.** Identical ink, greys, surfaces, and type across every product. This is what makes the suite feel like one family.
3. **One accent hue per product** drives interactive states (active nav, selection, links, focus rings). Same skeleton, different personality — instantly tells Drive from Calendar while staying obviously MCAIT.

### Sources used to build this system
This system was reverse-engineered from MCAIT's own product code (read-only; the reader may not have access, but they are recorded here):
- **`github.com/Mc-AIT/mcait-ui`** — platform shell + admin UI (design tokens in `admin-ui/src/styles/globals.css`).
- **`github.com/Mc-AIT/mcait-drive-drive-ui`** — the Drive product (full React app; `src/styles/index.css` is a 2,500-line themed stylesheet — gold brand + blue accent).
- **`github.com/Mc-AIT/mcait-cowork`** — the agentic hub (PRD + frontend design spec under `docs/`).
- Component foundation patterns informed by **`github.com/shadcn-ui/ui`**.

Explore those repositories further to design with higher fidelity against the live products.

---

## Content fundamentals

How MCAIT writes copy:

- **Voice:** confident, calm, and precise — *premium govtech meets consumer-friendly*. Trustworthy without being stiff. Never hypey.
- **Person:** address the user as **you**; the product refers to itself by name ("Cowork can…", not "I can…" or "we"). System/agent messages are matter-of-fact.
- **Casing:** **Sentence case everywhere** — buttons, menus, titles, table headers ("Share with people", "New folder", "Last modified"). Reserve Title Case for product names (Cowork, Drive). ALL-CAPS only for tiny eyebrow labels with letter-spacing (e.g. `STORAGE`, `RECENT`).
- **Length:** terse. Buttons are 1–2 words ("Share", "New", "Upload"). Empty states are one friendly sentence + one action.
- **Numbers & metadata:** technical metadata (IDs, sizes, timestamps, hashes) is set in **JetBrains Mono**. Humanize where it helps ("2 hours ago", "1.4 GB").
- **Emoji:** **none** in product UI. Iconography does that job.
- **Tone examples:**
  - Primary CTA: **"New"**, **"Share"**, **"Upload"**, **"Ask Cowork"**
  - Empty state: *"Nothing here yet. Upload a file or create a folder to get started."*
  - Confirmation: *"Move 3 items to Trash?"* → **"Move to Trash"** / **"Cancel"**
  - Agent: *"I found 4 documents that mention the Q3 budget. Want a summary?"*

---

## Visual foundations

**Type.** Three families, shared by every product:
- **Syne** — display & brand voice (hub greetings, hero numbers, marketing). Tight tracking (`-0.03em`), weights 600–800.
- **Manrope** — all body & UI text. Weights 400–700.
- **JetBrains Mono** — IDs, sizes, timestamps, code, technical metadata.

**Color.** oklch throughout. Cool neutrals on hue 265. Gold brand ≈ `#b8860b` (`oklch(0.62 0.13 80)`), used sparingly. Per-product accents are spread around the wheel so no two collide. Semantic colors (success/warning/danger/info) are shared.

**Backgrounds.** Clean and light — `--mc-canvas` (near-white, faint cool tint), cards on pure white. **No** gradient-heavy hero backgrounds, **no** purple-blue AI gradients. The only place color floods is intentional brand moments (the gold seal, a Cowork greeting). Subtle radial gold wash is acceptable behind the hub greeting only.

**Spacing.** 4px base scale (4/8/12/16/24/32/48/64). Generous gutters; dense data tables.

**Corner radii.** Soft but not pill-everything: `--radius-sm` 8px (inputs, small controls), `--radius-md` 12px (buttons, menus), `--radius-lg` 16px (cards), `--radius-xl` 20px (modals, large panels). Pills (`999px`) only for badges, chips, and avatars.

**Cards.** White surface, `--radius-lg`, a hairline `--mc-border` (≈ `oklch(0.91 …)`), and `--shadow-sm`. They lift to `--shadow-md` on hover with a faint upward translate. No heavy drop shadows; no colored left-border accent cards.

**Borders.** Hairline cool-grey (`--mc-border`). Strong variant (`--mc-border-strong`) for active/focused dividers. 1px throughout.

**Shadows.** Cool-tinted, very subtle. Three tiers (sm/md/lg) plus a `--shadow-focus` accent ring (3px soft accent halo) for keyboard focus.

**Hover states.** Neutral surfaces darken slightly (move to `--mc-canvas-2`); accent buttons go to `--mc-accent-hover`; cards gain shadow + 1px lift. Links underline.

**Press states.** Subtle scale-down (`transform: scale(0.98)`) + remove lift. Never a jarring color flip.

**Motion.** Restrained and quick. `--ease-out` `cubic-bezier(0.22,1,0.36,1)`, durations 160–240ms. Fades and short slides; **no** bounces, **no** infinite decorative loops. Respect `prefers-reduced-motion`.

**Transparency & blur.** Sparingly — sticky top bars and menus over content use a `backdrop-filter: blur(8px)` with a translucent white. Otherwise surfaces are opaque.

**Imagery.** Neutral, real, slightly cool. File thumbnails and avatars are the main imagery. No stock-photo gradients.

**Focus.** Always visible: 3px `--shadow-focus` accent halo, never `outline: none` without a replacement.

---

## Iconography

- **System:** **Lucide** (the icon set MCAIT's own code already uses — `lucide-react` in Drive, hand-rolled Lucide-style SVGs in the admin shell). Outline style, `currentColor`, rounded joins/caps.
- **Stroke weight:** Drive uses **1.5** at 16–20px; the platform shell uses **1.75** at 24px. Default to **1.5px** stroke, **20px** size in components.
- **Delivery:** load Lucide from CDN (`lucide@latest`) and render `<i data-lucide="name">`, or use inline SVG paths. **Never** hand-draw bespoke icons or substitute emoji/unicode glyphs.
- **Brand seal:** the one custom mark — a rounded-square gold seal with the "M8" / MCAIT monogram. Stored in `assets/`.
- **Emoji:** not used in product UI.

---

## Index / manifest

**Root**
- `styles.css` — global entry point (imports only). Consumers link this.
- `tokens/` — `fonts.css`, `colors.css`, `typography.css`, `spacing.css`, `products.css` (per-product accent themes).
- `assets/` — brand seal, logos, imagery.
- `guidelines/` — foundation specimen cards (Type, Colors, Spacing, Brand).
- `components/` — reusable React UI primitives (see below).
- `ui_kits/` — full-screen product recreations.
- `SKILL.md` — Agent-Skills-compatible entry point.

**Components** — `components/core/`: Button, Input, Badge, Card, Avatar, Tabs, Switch, Alert, **Sidebar**, and **AppBar** — the standard product top bar (branded mark · optional search/controls slot · identity widget). The AppBar embeds **`MCAITWidget`**: the shared identity cluster that anchors the right edge of every product and is the constant signature of MCAIT inside each belonging app. `Seal` and `MCAIT_APPS` are exported alongside it.

The widget has four parts, left to right:
1. **M8 seal** — the constant gold brand mark; signals you are inside the MCAIT platform.
2. **Cowork** — opens the agentic assistant inline, from any product.
3. **Product selector (apps grid)** — *the core feature*. A 3-column popup grid that switches between every MCAIT product (Drive, Calendar, Meet, Notebook, Mail, Aura), with the current product highlighted in its accent. This single, identical control in every app is what makes the suite feel like one account — one click moves the user across the whole family. Override the list via the `apps` prop (defaults to `MCAIT_APPS`); handle switches with `onNavigate(appId)`.
4. **Account** — the signed-in user menu (profile, settings, privacy, sign out).

Because the widget already carries account + app switching, products that adopt the AppBar drop the user tile and standalone product switcher from their sidebars.

**Sidebar** is the standard collapsible product nav rail: an optional featured *volume* card (name · mono badge · usage meter) above a list of icon+label nav items, with a collapse/expand toggle pinned to the bottom. It collapses to a 64px icon-only rail. Controlled (`collapsed` + `onToggle`) or uncontrolled (`defaultCollapsed`); accent follows the product theme via `data-product`.

**Inset-panel shell (core layout).** Every product uses the same frame: the shell (the element behind the app bar + sidebar) is `--mc-surface` (white); the **AppBar carries no bottom hairline** (pass `divider={false}`) and the **sidebar carries no right border**; instead the **content area alone** draws a top + left border and a `--radius-lg` **top-left corner**, so it reads as one flat panel tucked inside the white shell. Apply this to every sidebar in every app — do not put borders on the top bar or sidebar.

**UI kits** — `ui_kits/cowork/` (agentic hub), `ui_kits/drive/` (file storage).

---

## Caveats

- **Fonts** (Syne, Manrope, JetBrains Mono) load from Google Fonts — the source repos ship no binaries. To air-gap, self-host the woff2 files and swap the `@import` in `tokens/fonts.css` for local `@font-face` rules.
- Per-product accents for Calendar / Meet / Notebook / Mail are defined as tokens but only Cowork + Drive have full UI kits so far.
