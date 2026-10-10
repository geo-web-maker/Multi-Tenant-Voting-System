# BallotBox — Blueprint Console: a second UI template behind an env switch

**Goal.** Add the look in `kes-blueprint-console-mockups.html` as a **second, complete UI template** that a deployment turns on with one environment variable. **Today's UI stays the default** and does not change when the variable is unset.

**How to use this file.** It is written the same way as `BALLOTBOX_PHASE_RUNBOOK.md`: read §0–§7 once, then hand the AI **one card from §8 per session** with the §2 prompt from the runbook. Put this file in the repo root next to the runbook; per-card notes go in `progress/BP-*.md`.

**Status of this document.** Written from a read of the uploaded zip and mockup. The sandbox it was written in had no network, so `npm ci`, `vitest`, `eslint` and `vite build` were **not run**, and the code in the appendices is **unexecuted reference**. The gates in §9–§10 exist to catch what reading cannot. The contrast numbers in §5.6 *were* computed (WCAG formula) from the mockup's colour values.

---

## 0. Summary

| | |
|---|---|
| **Switch** | `VITE_UI_TEMPLATE=blueprint` (build-time, per deployment). Unset, empty, or any other value = today's UI. |
| **Mechanism** | `main.jsx` loads one extra chunk (blueprint CSS + a few React components) **only** when the variable equals `blueprint`, registers it, and sets `data-template="blueprint"` on `<html>`. Existing components check the registry at render time and either run their **unchanged** current code or hand off to the blueprint piece. |
| **Four seam kinds** | **S1** token bridge (remap existing CSS variables) · **S2** fallback tokens (`#2ecc71` → `var(--bp-ok-solid, #2ecc71)`, pixel-identical by default) · **S3** neutralisers (a small, fenced block of `!important` CSS) · **S4** component swap (header, sidebar, OTP cells, ballot dock…). |
| **Fidelity** | **Tier A** (screens/chrome the mockup draws) = match the mockup spec exactly. **Tier B** (the ~60 panels it does not draw) = inherits colour, type, radius, spacing through S1–S3, and is reviewed screen by screen. Nothing is allowed to be unreadable or unusable. |
| **Proof of "default unchanged"** | (1) default render has no `data-template` and no `bp-` class; (2) default build contains no blueprint chunk and its entry chunk grows by ≤ 1.5 KB gzip; (3) full existing suite green. |
| **Proof of "blueprint works"** | The **whole existing test suite re-run with the template on** (§9 L3b), plus token/contrast/parity tests, plus a screen-by-screen visual check against the mockup's own deep links (§12). |

---

## 1. Rules (apply to every card)

| # | Rule |
|---|---|
| R1 | **Default is sacred.** With the variable unset the app renders the same elements, classes and pixels as today. Only permitted default-path edits: new tiny files (`template.js`, `templateChrome.js`), the guarded activation in `main.jsx`, seam branches that fall through to the old code, extra `className`s (additive), and S2 literal→`var(--bp-x, <same literal>)` swaps. |
| R2 | **Build-time, one value, strict.** Only the exact string `blueprint` activates it. No runtime/user toggle: one tenant must never show two designs. |
| R3 | **Visual layer only.** No change to API calls, state, handlers, session/local-storage keys (incl. `theme`), analytics, `data-track`, `data-phase`, `data-field`, ids, or backend. |
| R4 | **Copy is frozen.** Every existing user-visible string stays as is (tests, help text and support scripts depend on it). The mockup's strings ("Verify & Continue", "Review Ballot", "Election 2026 · Blueprint", …) are **illustrative**. New strings only for new chrome, listed in §7. |
| R5 | **No new dependencies** (runbook rule). No fonts to download: the mockup uses `system-ui` + `ui-monospace` stacks, which also suits Slow 3G. |
| R6 | **Tokens only.** No hex/rgb literals in blueprint files outside the token block. New UI written elsewhere while this is in progress uses `var(--…)` and adds no new hex. |
| R7 | **`!important` only inside the fenced NEUTRALISERS section** of `blueprint.css`, each with a comment naming the inline style it beats (`file:line`). |
| R8 | **Print is protected.** All visual blueprint CSS sits in `@media screen`; token declarations are the only exception. The official documents (results, report, certificate) print identically in both templates. |
| R9 | **Behaviour parity net.** `VITE_UI_TEMPLATE=blueprint npm test` runs the *entire* existing suite; it must pass. A failure is a blueprint bug unless §7 records the deviation. |
| R10 | **Accessibility floor:** WCAG 2.2 AA — text ≥ 4.5:1 (large text ≥ 3:1), control boundaries ≥ 3:1, 48 px targets (44 px floor), visible focus, `prefers-reduced-motion` honoured. |
| R11 | **One breakpoint: 768 px** — the same as `TabBar`'s `MOBILE_QUERY` and `index.css`. The mockup's `.m` class means `@media (max-width: 768px)`. |
| R12 | **Hooks rule.** A seam never early-returns inside a component that uses hooks. Rename the existing component `DefaultX` (body untouched) and export a thin wrapper `X` that chooses (see §4.5). |
| R13 | **Runbook hygiene:** one card per session, tests first, commit green, `progress/BP-<ID>.md`, never open or print any `*.env` file, never run against production. |

---

## 2. What the code looks like today (these facts drive the design)

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F1 | Styling is almost entirely **inline style objects** with CSS variables. | 2,364 `style={` in `App.jsx` + `components/`; 391 hex literals; ≈ 800 `var(--…)` uses (`--border-color` 226, `--text-color` 185, `--success` 89, `--card-bg` 85, `--danger` 70, `--warning` 66, `--bg-color` 58, `--info` 53). | A stylesheet can't restyle most things without `!important`. Remapping variables (S1) reaches the `var()` users for free; hex literals need S2. |
| F2 | Theme = `data-theme` on `<html>` (`App.jsx` ≈ 213–222; localStorage key `theme`; OS preference as fallback in `index.css`). | | Blueprint tokens key on `html[data-template="blueprint"][data-theme=…]` **and** mirror the `prefers-color-scheme` fallback. |
| F3 | Org branding is written **inline on `<html>`**: `--brand-primary`, `--brand-accent` (`App.jsx` ≈ 316–318). | Inline custom properties beat stylesheet rules. | Only a stylesheet `!important` can pin them (neutraliser N1). Decision D1. |
| F4 | Public pages are a **500 px centred column with the nav inside it**; `containerStyle` adds 20 px padding and `minHeight:100vh`. | `App.jsx` ≈ 706–738, ≈ 1187. | The mockup wants a **full-width sticky header** and a **520 px** content column → column/container neutralisers + header swap. |
| F5 | Good **single seams** exist: `TabBar` (every dashboard), `AdminHeader` (every admin panel), `PhaseBanner`, `OtpInput`, `BallotBox`, `Results`, `ApplicantPortal`. | | Few files carry most of the visible chrome. |
| F6 | **Grouped** dashboards (SuperAdmin, Commission) already use `.dash-body` (rail + content). **Flat** ones (IT Admin, Finance, Overseer, Vetting) put the tab row *inside* the shell. | `grep -n "dash-body\|<TabBar" src/components/*Dashboard.jsx` | The mockup's sidebar layout needs a small frame component for the four flat dashboards (card T7b). |
| F7 | `TabBar` switches layout in **JS at 768 px** and `index.css` mirrors it; a comment warns of drift. | `TabBar.jsx` `MOBILE_QUERY`. | Blueprint layout is **CSS-only** at the same 768 px. |
| F8 | The OTP field is **one `<input autoComplete="one-time-code">`** with a paste-tolerant `cleanOtp` (no `maxLength`). | `OtpInput.jsx`. | The mockup's 6 boxes must be **presentation over the one input**, never six inputs (would break SMS autofill and pasting "123 456"). |
| F9 | Hex hotspots: `PhaseBanner` `THEME`, `BallotBox` (`#3b82f6`, `#1e293b`), `Results` banner (`#10b981`, `#f0fdf4`…), `OtpInput` (`#e74c3c`, `#2ecc71`), `App.jsx` buttons. Top literals: `#fff` 46, `#2ecc71` 37, `#e74c3c` 36, `#64748b` 17, `#3b82f6` 15, `#10b981` 12, `#e67e22` 11, `#3498db` 11. | | These need S2 (or S4) to follow the template. |
| F10 | The **print system** depends on class names (`.position-header`, `.print-only`, `.no-print`, `.outer-wrap`, `.dashboard-shell`, `.dash-body`, `.dash-main`) and overrides the colour variables with `!important` in `@media print`. | `index.css`. | Keep those classes; keep blueprint visuals out of print. |
| F11 | Tests find things by **role/name/text**, `data-phase`, `data-track`; `scripts/check_data_track.py` requires 7 labels (`login-submit`, `apply-submit`, `help-fab`, `otp-submit`, `ballot-submit`, `phase-apply-now`, `export-register`). | | Blueprint markup must keep every one; the script also scans new `.jsx` under `src/templates/`. |
| F12 | The mockup's **navigation contents are not the real ones** (see §6.2). | | The mockup is a *design* reference, not the information architecture. Navigation always comes from the real tab arrays. |
| F13 | The mockup is **KES-specific** ("KES" stamp, name, orange/navy palette); the system is multi-tenant. | | Decision D1 (palette) and an `initials(orgName)` helper. |
| F14 | The mockup's **frame behaviour is tooling**, not UI: fixed 800 px device frame with internal scrolling, toolbar, scaler, "Spacing & tint spec" page, Guides overlay. | | Not shipped. Production uses normal document scroll; the spec page's numbers become acceptance criteria. |
| F15 | Charts are **inline SVG** (`UsageCharts.jsx`, `HeatmapOverlay.jsx`), not chart.js. | `grep -rln "<svg" src/components` | Colours live in JS attributes; use S2 (`style={{fill:'var(--bp-ac, <old>)'}}`). |
| F16 | Two public pages render **outside the App shell**: `/status/<token>` (`CandidateStatusPortal`, 39 hex) and `/verify/<id>` (`VerifyCertificate`). | `App.jsx` early returns. | They get tokens + page background only (no title-block header) unless you decide otherwise (D9). |
| F17 | `AdminDashboard.jsx` (642 lines, 27 hex) is **not imported by `App.jsx`**. | `grep -n AdminDashboard src/App.jsx` | Treated as legacy and **out of scope**; confirm with that grep in T0. |
| F18 | `.gitignore` already ignores `.env`, `.env.*`, `*.env`. | | Do **not** create `.env.blueprint`; pass the variable on the command line (§4.1). |

---

## 3. Decisions for you (recommended defaults; each is reversible)

| # | Decision | Recommended | Why / what changes if you flip it |
|---|---|---|---|
| **D1** | **Palette source.** Fixed mockup palette (orange accent, navy dark) vs the organisation's own `primary_color`/`accent_color`. | **Fixed palette** for v1; org logo and name still come from branding. | The mockup palette is the one whose contrast was verified (§5.6). Another tenant's arbitrary colours can fail AA. Flip later (backlog B1) with a contrast-gated accent derivation; the §9 contrast helper is reusable. |
| **D2** | **Control-boundary contrast.** The mockup's `--line` is 1.49:1 (light) / 1.53:1 (dark) against card surfaces, below the 3:1 WCAG 2.2 asks for input/OTP/tick boundaries. | **Add `--bp-line-ui`** (light `#7c8696`, dark `#6f90bd`; ≥ 3.3:1 / ≥ 3.4:1 on all three surfaces) for interactive control borders only; keep `--bp-line` for dividers/cards. | Slightly darker input outlines than the mockup. Set `--bp-line-ui` equal to `--bp-line` to match the mockup exactly (the contrast test then fails, by design). |
| **D3** | **Accent text placement.** Light accent `#c2410c` is 5.18:1 on cards but **4.37:1 on the page background and 4.48:1 on the accent tint**. | **Rule:** accent-coloured *text* only on card surfaces (`--bp-sf`, `--bp-sf2`, `--bp-sf3`); on the page background or tints use `--bp-tx`. Large text (≥ 24 px, e.g. `.bp-big`) is exempt (3:1). | Enforced by the contrast test list. |
| **D4** | **Tier B content pane.** Dashboard panels the mockup does not draw sit inside one card (`.dashboard-shell` styled as the mockup `.card`). | **Yes.** | Gives every legacy panel a legible surface with no per-panel work. Individual panels can be promoted to their own cards later. |
| **D5** | **"Sheet NN / NN" cell** (mockup page index). | Consoles: *active tab index / tab count*. Voter flow: *step n / 3*. Results, Apply: hide the cell. | Keeps the drawing-sheet idea where an index exists. Alternative: drop the cell entirely. |
| **D6** | **Logo.** Mockup shows initials in a 40 px accent stamp. | Show the org's **logo image inside the stamp** (contained) when `logo_url` exists; otherwise `initials(orgName)`. | Wide wordmark logos get letterboxed in a square: HUMAN-check with real tenant logos. |
| **D7** | **Tablet band 769–1023 px** (the mockup shows only 1280 and 390). | Stat grids 4→2 columns and `.bp-two` stacks below 1024 px. | Extension recorded in §7 (E-items). |
| **D8** | **Where the template is shown.** | App-shell pages + dashboards. | See D9. |
| **D9** | `/status/<token>` and `/verify/<id>` (outside the shell). | **Tokens and page background only**; no header. | Header would need the org context that those pages deliberately avoid loading. |

---

## 4. Architecture

### 4.1 The switch

* Variable: **`VITE_UI_TEMPLATE`**. Accepted: `blueprint`. Everything else (unset, empty, `default`, `Blueprint`, ` blueprint `) → default. Strict equality on purpose: the bundler can only drop dead code for an exact literal comparison.
* Vite inlines `VITE_*` at **build** time → changing it needs a **redeploy**. In this project every tenant is its own deployment (`VITE_ORG_SLUG` works the same way), so the template is chosen **per tenant**. `VITE_*` values are public (they end up in the bundle) — fine for a design name.
* Add to `frontend/.env.example` only (never open real env files):
  ```
  # UI template. Leave empty for the standard UI; "blueprint" for the Blueprint Console look. Build-time: redeploy after changing.
  VITE_UI_TEMPLATE=
  ```
* Local use (no `.env.blueprint` — it would be git-ignored):
  ```bash
  VITE_UI_TEMPLATE=blueprint npm run dev                       # bash / zsh / git-bash
  # PowerShell:  $env:VITE_UI_TEMPLATE='blueprint'; npm run dev
  VITE_UI_TEMPLATE=blueprint npx vite build --outDir dist-blueprint
  VITE_UI_TEMPLATE=blueprint npm test                          # the parity net (L3b)
  ```
* Vercel: add the variable to the project's Environment Variables (Preview first, then Production), redeploy.

### 4.2 Files

```
frontend/
  design/blueprint/kes-blueprint-console-mockups.html   # committed design source of truth, NOT bundled
  scripts/check_template_build.sh                       # §10 gate
  src/
    template.js                 # resolver + registry (always bundled, ~0.6 KB)
    templateChrome.js           # tiny store: crumb / tab index / logout for the header (always bundled, ~0.5 KB)
    test/template.js            # useBlueprint()/useDefault() helpers
    templates/blueprint/        # ← loaded ONLY in blueprint builds
      index.js                  # imports blueprint.css, exports the components below
      blueprint.css
      TitleBlockHeader.jsx      # public header + console header (brand · nav|crumb · status · sheet)
      ConsoleSidebar.jsx        # grouped nav (desktop rail / mobile pill row)
      ConsoleFrame.jsx          # .dash-body wrapper for flat dashboards
      BottomDock.jsx            # ballot actions
      OtpCells.jsx              # 6 presentation cells over the one real input
      primitives.jsx            # Pill, StepBar, Meter, Stat, Banner, Stamp, initials()
      *.test.js(x)              # token, parity, render tests
```

Only `template.js` and `templateChrome.js` are statically imported by default code. **Nothing under `templates/blueprint/` may be imported statically from outside that folder** (it would drag blueprint code into the default bundle). Enforced by test L5-a.

### 4.3 Activation (`main.jsx`)

```jsx
import { setTemplateImpl } from './template.js'
// …existing imports…

async function start() {
  consumeViewAsHandoff()                       // existing line, still first
  // Exact literal comparison: the bundler removes this whole branch (and the blueprint chunk) from default builds.
  if (import.meta.env.VITE_UI_TEMPLATE === 'blueprint') {
    try { setTemplateImpl(await import('./templates/blueprint/index.js')) }
    catch (err) { console.error('Blueprint template failed to load — using the standard UI.', err) }
  }
  createRoot(document.getElementById('root')).render(/* …unchanged tree… */)
}
start()
```
* A failed chunk load **falls back to the default UI** instead of a blank page.
* The template is registered **before** the first render, so there is no flash of the wrong design.
* `templates/blueprint/index.js` also sets `viewport-fit=cover` on the viewport `<meta>` at import time (needed for `env(safe-area-inset-*)` on notched phones). It does this **only in blueprint**, because adding it to `index.html` would change the default template on notched phones.

### 4.4 Registry and chrome store (always bundled; keep tiny)

See Appendix A for the code. Contract:

* `getTemplate()` → `null` (default) or the blueprint module. Seams call it **at render time** (not at import time), which is what makes the test helpers trivial.
* `templateChrome.js` is a 20-line `useSyncExternalStore` store holding `{ role, group, tab, tabIndex, tabCount, onLogout }`. `ConsoleSidebar` publishes the crumb; `AdminHeader` publishes `onLogout`; the console header reads both. It exists so the sticky header (owned by `App`) can show the active tab (owned by each dashboard) without prop-drilling through six dashboards.

### 4.5 The four seam kinds (use the lowest that reaches the mockup)

| Seam | What it is | Use for | Cost on default |
|---|---|---|---|
| **S1 Token bridge** | `blueprint.css` re-points existing variables (`--card-bg: var(--bp-sf)` …). No JS change. | Everything that already uses `var(--card-bg)`, `--text-color`, `--border-color`, `--success`… | none |
| **S2 Fallback tokens** | Replace a literal in default JS with `var(--bp-ok-solid, #2ecc71)`. Default pixels identical (the variable is undefined there); blueprint defines it. | Hex literals (F9) on any screen. | inline style *string* differs, pixels don't |
| **S3 Neutralisers** | A fenced block of `!important` rules beating inline layout (`containerStyle` padding, 500 px column, `.outer-wrap` padding, `.dashboard-shell` card). | Layout props that cannot be tokenised. Keep the block < 25 rules. | none |
| **S4 Component swap** | Existing component stays; a thin wrapper chooses. | Chrome that differs structurally: title-block header, sidebar, OTP cells, ballot dock, results meters. | wrapper + early branch |

S4 pattern (R12):

```jsx
// TabBar.jsx — the existing component is renamed, body untouched
function DefaultTabBar(props) { /* …today's code… */ }

export default function TabBar(props) {
  const bp = getTemplate();
  return bp ? <bp.ConsoleSidebar {...props} /> : <DefaultTabBar {...props} />;
}
```
Blueprint components receive the **same props** and call the **same handlers**; they only render differently. No logic is duplicated.

### 4.6 CSS layering inside `blueprint.css`

1. **TOKENS** — `--bp-*` values per theme, plus the `prefers-color-scheme` fallback for the moment before `data-theme` is set (Appendix B).
2. **BRIDGE (S1)** — legacy variables → `--bp-*`.
3. **BASE** — page grid background, headings (mono, uppercase), `label`, `input/select/textarea`, `button` shape, tables, focus ring. Element-level rules are scoped `html[data-template="blueprint"] …`.
4. **COMPONENTS** — the ported mockup classes, renamed `bp-*` (Appendix C). Unscoped is fine: the class exists only in blueprint DOM.
5. **RESPONSIVE** — one `@media (max-width: 768px)` block holding the mockup's `.m …` rules, plus the tablet band (D7).
6. **NEUTRALISERS (S3)** — fenced with `/* ===== NEUTRALISERS ===== */ … /* ===== /NEUTRALISERS ===== */`.
7. **PRINT** — a tiny `@media print` reset (grid off, `text-transform:none`, tokens forced light).
All of 3–6 inside `@media screen`.

### 4.7 Bundle isolation

* Default build: no file with `blueprint` in its name; no `bp-` strings in any emitted JS; entry chunk ≤ baseline + 1.5 KB gzip.
* Blueprint build: blueprint chunk (JS + CSS) ≤ 30 KB gzip; entry chunk ≤ default + 2 KB gzip.
* If the default build **does** contain the chunk, replace the shared constant with the literal comparison at each import site (already done in `main.jsx`) — that is the only dynamic import, so this should not occur; the gate proves it.

---

## 5. The design to reproduce (extracted from the mockup)

### 5.1 Tokens (mockup name → production name `--bp-<name>`)

| Token | Light | Dark | Use |
|---|---|---|---|
| `bg` | `#e9ecef` | `#0b2545` | page background (with 24 px grid) |
| `sf` | `#ffffff` | `#10335f` | card |
| `sf2` | `#f1f3f5` | `#0d2b52` | input / inset / bar track |
| `sf3` | `#ffffff` | `#143b6e` | raised: header, sidebar, dock |
| `line` | `#ced4da` | `#2b4f80` | dividers, card borders |
| `line-ui` *(new, D2)* | `#7c8696` | `#6f90bd` | interactive control borders |
| `tx` | `#14213d` | `#e8f0fb` | text |
| `mu` | `#5c677d` | `#a3b8d4` | muted text |
| `ac` | `#c2410c` | `#ff922b` | accent |
| `ai` | `#ffffff` | `#0b2545` | ink on accent |
| `ok` / `wn` / `no` | `#1b6e2f` / `#8f4d00` / `#b42323` | `#69db7c` / `#ffc078` / `#ffa3a3` | status **ink** (text/border on a tint — *not* solid fills, see F-note below) |
| `grid` | `rgba(20,33,61,.06)` | `rgba(255,255,255,.05)` | page grid lines |
| `sh` | `0 8px 24px rgba(11,37,69,.10)` | `0 8px 24px rgba(0,0,0,.35)` | shadow (dark mode lifts surfaces instead) |

**Precomputed tints** (the mockup uses `color-mix()`, which older Android WebViews lack; precomputing is identical and testable): 

| | Light | Dark |
|---|---|---|
| `tint` (accent 10% over `sf`) | `#f9ece7` | `#283c5a` |
| `tint2` (accent 18%) | `#f4ddd3` | `#3b4456` |
| `ok-tint` / `wn-tint` / `no-tint` / `mu-tint` (10% over `sf`) | `#e8f0ea` / `#f4ede6` / `#f8e9e9` / `#eff0f2` | `#194462` / `#284162` / `#283e66` / `#1f406b` |
| pill/banner edge | status colour at 35% alpha: `rgb(r g b / .35)` | same |

> **F-note on status colours.** The mockup's `ok/wn/no` are *ink* colours chosen to read on a 10% tint. The current code also uses `var(--success)`, `--danger`, `--warning` as **solid fills** with fixed text colours (e.g. `index.css` `.tabbar-pill.is-active`: dark text on `--success`). In light mode `#1b6e2f` + dark text fails. T9 audits every solid use (`grep -rn "background[^;]*var(--\(success\|danger\|warning\)"`) and gives the offenders S2 tokens `--bp-ok-solid` etc. with a verified ink colour.

### 5.2 Spacing and size (4 px base, 8 px rhythm — *only* these steps)

`s1 4 · s2 8 · s3 12 · s4 16 · s5 24 · s6 32 · s7 48`. Gutter/pad: **24** desktop, **16** mobile. Header **64** (mobile **56** + a tab row). Tap target **48** (`.bp-btn.sm` 40; side links 40, mobile 44). Radius **12** (cards) / **8** (inputs, small) / **99** (pills, buttons) / **28** (dock, mobile pill nav). Header outer margin 12, cell padding 16. Card gap 16. Section label 24 above / 12 below.

### 5.3 Typography

Body `14/24 system-ui`. Headings `h1 24/32`, `h2 16/24`, **monospace** (`ui-monospace, Menlo, Consolas`), **uppercase**, `letter-spacing .02em`. Labels: mono 12/16, 700, uppercase, `.06em`, muted. Header title: mono 12/16 700 uppercase `.06em`; subtitle 11 muted. Numbers use mono. Big stat: mono 800 40/48 (mobile 32/40) in accent.

### 5.4 Component catalogue (mockup class → production class → where it is used)

| Mockup | Production | What it is / rule |
|---|---|---|
| `.top` | `.bp-top` | **Drawing title block.** Sticky, 64 tall, 12 outer margin, 1 px border, radius 12, shadow; cells separated by **dashed** dividers; a **ruler edge** (`.bp-rule`: 1 px ticks every 8 px, accent ticks every 48 px) along the bottom. |
| `.tl .logo .bt` | `.bp-tl .bp-logo .bp-bt` | Brand cell: 40 px accent stamp inside a **dashed registration frame** (`inset:-4px`), name (mono 12 uppercase, ellipsis) + subtitle. |
| `.top nav a(.on)` | `.bp-nav` | Public nav: 40 px pills, active = accent fill. Real labels (Vote Now / Live Results / Apply). `aria-current="page"` on the active one. |
| `.crumb` | `.bp-crumb` | Console breadcrumb `group / tab`; hidden < 769 px. |
| `.cell` | `.bp-cell` | Status cell (`● Voting Open`) and sheet cell (`03 / 18`); small labels hidden on mobile. |
| `.card` | `.bp-card` | `--bp-sf`, 1 px line, **3 px accent top border**, radius 12, padding = gutter, shadow. |
| `.in(.f)` | `.bp-in` | 48 px field on `sf2`, border `line-ui`; focus = 2 px accent outline, offset 1. Labels above (D-note: real fields that only have a placeholder get a real `<label>`). |
| `.btn(.g .sm)` | `.bp-btn` | 48 px pill; primary = accent/ink; ghost = transparent + line-ui border; `sm` = 40 px inline. |
| `.lnk` | `.bp-lnk` | Centred accent link (D3: only on card surfaces). |
| `.ban(.w)`, `.alt` | `.bp-ban`, `.bp-ban.bp-warn`, `.bp-alt` | Tinted notices with **4 px left border**: ok / warn / error. Extensions `.bp-ban.bp-mute` (muted) and `.bp-ban.bp-acc` (accent) for the other two phase states (§7 E2). |
| `.pos` | `.bp-pos` | Position label: accent pill, mono uppercase. |
| `.cand(.on)` `.av` `.tick` | `.bp-cand` | 72 px row card; 48 px avatar; 28 px tick; selected = accent border + 2 px outline + `tint`. |
| `.dock` | `.bp-dock` | Floating pill bar (radius 28) with two buttons; fixed to the bottom, safe-area aware; publishes its height to `--bottom-bar-height` so the Help FAB clears it. |
| `.big .stat` | `.bp-big`, `.bp-stat` | Stat cards (3-up desktop, 2-up mobile `.k`). |
| `.pill(.w .n .m)` | `.bp-pill` | 24 px status pill: ink text, 10% tint, 35% edge. |
| `.row .t .bar` | `.bp-meter` | Result/turnout rows: label + `value · pct%`, 8 px bar (winner = accent, others muted). |
| `.shell .side .main` | `.bp-shell .bp-side .bp-main` | Console: 240 px sidebar + content. Mobile: sidebar becomes a **bottom pill row** (`order:2`, radius 28, horizontal scroll). |
| `table.rs` | `.bp-table` | Mobile **card-rows**: header hidden, each row a bordered block, cells labelled via `data-l`. |
| `.otp i` | `.bp-otp` | 6 cells 48×56 (mobile 44×52). **Presentation only (F8).** |
| `.steps i` | `.bp-steps` | Segmented progress, 8 px pills. |
| `.cen` | `.bp-cen` | Boot/centred screen: card max 384, 72 px stamp. |
| `.chart`, `.hot` | `.bp-chart`, `.bp-hot` | Bar chart and hotspot grid colours. |
| `.two`, `.grid(.g2 .g4 .k)` | `.bp-two`, `.bp-grid…` | Layout grids. |
| `.chip` | `.bp-chip` | Small outlined tag. |
| `.dot` | `.bp-dot` | Pulsing status dot (disabled under reduced motion). |
| `.dev` grid | `body` | 24 px grid background on the page (`background-attachment: fixed`). |

Not ported (tooling): `.tb`, `#st`, `#sc`, `.dev` frame/scaler, `.gd` Guides overlay, `.sp`/`.sw` spec page, the page `<select>`.

### 5.5 Responsive rules

* The mockup's `.m` class → `@media (max-width: 768px)`; its `--gut/--pad/--hh` overrides move into that block.
* Public header on mobile: brand row 56 + nav row (full-width pills) under a dashed divider; sheet cell hidden.
* Console on mobile: crumb hidden; sidebar → bottom pill row; stat grids 2-up (`.k`) or 1-up; `table.rs` → card-rows.
* Tablet band (D7): `<1024px` → `.bp-g4` 2 columns, `.bp-two` 1 column.
* Inputs ≥ 16 px on mobile (the existing rule in `index.css` prevents iOS zoom — keep it).

### 5.6 Contrast (computed with the WCAG formula)

Mockup claims confirmed: text on card 15.97 / 11.01; muted on card 5.69 / 6.24; button text on accent 5.18 / 6.89; accent on card 5.18 / 5.66; status ink on tint 5.45–5.61 / 5.59–6.46.
**Gaps the mockup's table does not cover** (handled by D2/D3):

| Pair | Light | Dark | Verdict |
|---|---|---|---|
| accent text on page `bg` | **4.37** | 6.89 | light fails 4.5 → D3 |
| accent text on accent `tint` | **4.48** | 4.99 | light fails 4.5 → D3 |
| `line` vs card (control boundary) | **1.49** | **1.53** | needs 3:1 → D2 |
| `line-ui` (new) vs `sf` / `sf2` / `sf3` | 3.68 / 3.31 / 3.68 | 3.85 / 4.31 / 3.40 | passes |
| muted on `bg` | 4.80 | 7.59 | passes |

---

## 6. Screen map

### 6.1 Tier A (match the mockup)

| Mockup page | Real source (use `grep -n` to re-anchor) | Seams | **Must keep** (the mockup omits it) |
|---|---|---|---|
| **boot** | `App.jsx` `BootSplash` (≈ 1110) + `boot*Style` consts | S4-lite (style map) + stamp | 4 stages and their dot colours; `VITE_ELECTION_NAME`/`VITE_LOGO_URL` fallbacks; exit fade; the spinner ring when there is no logo is replaced by the initials stamp. |
| **login** | `App.jsx` step 1 block (≈ 816–900), `PhaseBanner.jsx`, `VoterLoginInputs.jsx` | S2/S3 + S4 (PhaseBanner) | Admin-path fields (email, password, TOTP, show-password), Turnstile, `LoginErrorActions`, support link, "Are you an admin? Log in here", Apply-now button + countdown rows inside the banner, typing placeholder. If a field only has a placeholder, add a real `<label>` (reuse the placeholder text). |
| **otp** | `OtpInput.jsx`, step 2 block in `App.jsx` (≈ 920–940) | S4 (`OtpCells`) | One input with `autoComplete="one-time-code"`, `inputMode="numeric"`, paste tolerance, lock countdown (`role="alert"`), `wrong_code` / `no_live_code` messages, Back, resend timer, `data-track="otp-submit"`. Error → cells use `--bp-no`; locked → 50% opacity. |
| **ballot** | `BallotBox.jsx` (≈ 174–270, styles ≈ 418+) | S4 + S2 | Tap-to-toggle selection, preview banner and **hidden dock** when `isPreview`, Clear-All confirm modal, `faceCropUrl` photos (initials when no photo), orgName heading, the `position-header` **class** (print), `REVIEW & SUBMIT (n)` label and disabled-when-empty. `StepBar` is decorative (`aria-hidden`), 2 of 3 filled. |
| **review** | `BallotBox.jsx` `showSummary` modal (≈ 289+) | S4 style | It stays a **modal** (mockup draws a page). Countdown gating, double-tap lock (`castingRef`), "still sending", status check, `statusModal`. "Go Back" ghost button. |
| **done** | `BallotBox.jsx` success modal (≈ 371) + `ReceiptLink.jsx` | S2/S4 style | Check-mark draw animation (recoloured with tokens), receipt link/code. |
| **results** | `Results.jsx` (≈ 196–430) | S4 meters + S2 | All states (live / provisional / certified / not-started and the C1 states), polling, `.cand-row` structure, LEADING/WINNER labels, the whole `.print-only` document **untouched**. |
| **apply** | `ApplicantPortal.jsx` (≈ 300–600) | S2/S3 + `StepBar` | Field errors + `data-field`, photo and payment-proof uploads, fee modal link, payment method select, upload progress ("slow" note), status/polling views. `StepBar` shows **only while a submit runs**, bound to the existing `step` (1–4). The mockup's button copy is not used. |
| **sa / voters / chg / usage** | `SuperAdminDashboard.jsx`, `SharedAdminPanels.jsx`, `VoterStats.jsx`, `VoterList.jsx`, `SuperAdminStudentEdit.jsx`, `UsageCharts.jsx` | S4 shell + S2/S3 | Every control the mockup omits (filters, exports, bulk actions, modals). Charts stay SVG. |
| **it** | `ITAdminDashboard.jsx`, `ITAdminStudentEdit.jsx` | S4 frame | Roster-frozen states, request list counts. |
| **com / ov** | `CommissionDashboard.jsx`, `OverseerDashboard.jsx` | S4 shell | Read-only guarantees for the observer role. |
| **fin / vet** | `FinancialControllerDashboard.jsx`, `VettingDashboard.jsx` | S4 frame | Approve/reject flows, hat-switch button, counts. |

### 6.2 Navigation reality (mockup ≠ product) — always use the real arrays

| Role | Mockup shows | Real tabs (source) |
|---|---|---|
| Super Admin | Election Setup · People & Roles · Requests & Access · Security · Platform | Same groups (`tabGroups` in `SuperAdminDashboard.jsx` ≈ 839+); use the real full list. |
| Commission | Overview, Turnout, Audit Log · Student/Contact Changes · Final Report | Outcomes, Live Results · Student Changes, Contact Changes, Reset OTP (chief/deputy only) · shared tabs, Official Document. |
| IT Admin | Voters, Edit Student, Reset OTP | Overview, Voters, Add Student*, Edit Student, Remove Student*, My Requests (* hidden when roster frozen). |
| Finance | Voter payments, Candidate payments | Same two + shared tabs. |
| Vetting | Applications, My Votes, Panel | Pending, Resolved. |
| Overseer | Live Turnout, Alerts, Audit Log | Applications, Student Changes, Candidate Results, Contact Changes + shared tabs. |

Flat dashboards (no `groups`) are shown as **one group named after the role** (the mockup does the same: group `IT Admin`, `Payments`…).

### 6.3 Tier B (everything else)

Inherits through S1–S3: headings/labels/inputs/selects/buttons/tables inside `.dashboard-shell`, modals (`.modal-content`), toasts (`UIFeedback`), `ViewAsBanner`, help panel/FAB, Final Report UI, Security/SMS panel, Fee schedule, Timeline, Import review, Analytics, Heatmap overlay, Vetting Panel Manager, Candidate Status portal, Verify Certificate. Each gets a row in the **Tier B register** (`progress/BP-T9.md`): screen · light ok · dark ok · mobile ok · hex left · notes.

---

## 7. Deviations register (decide once, then it is not a bug)

| ID | Deviation from the mockup | Reason |
|---|---|---|
| E1 | Nav/tab labels, button text and headings use **real copy**. | R4. |
| E2 | Phase banner has **4 states** but the mockup draws 2 tint styles: `voting_open` → ok, `voting_soon` → warn, `apply_open` → accent tint (`.bp-ban.bp-acc`), `voting_closed` → muted (`.bp-ban.bp-mute`). Same construction (10% tint + 4 px left border). | Derived from `phase.js` states. |
| E3 | Header gains a **theme toggle** cell (labels `Light`/`Dark` as today) and the **Back to Admin** button. | Existing functions the mockup's toolbar did not show. |
| E4 | Console header: **no tab-name `<h1>` inside main**; the crumb shows it and panels keep their own headings. `AdminHeader` becomes a toolbar row (title, subtitle/Sync, actions, Refresh, Logout) above the shell. **Logout** also appears in the sidebar "Session" group. | Real panels carry Refresh/Sync/actions the mockup omits. |
| E5 | Review stays a **modal**. | Existing behaviour. |
| E6 | OTP is **one input with 6 presentation cells**. | F8. |
| E7 | `StepBar`: ballot (2/3, decorative) and apply (submit progress only). | Real flows differ from the mockup's. |
| E8 | `--bp-line-ui` added; accent-text rule. | D2, D3. |
| E9 | `--info` maps to the accent (the mockup has no blue). | Bridge. |
| E10 | Tab labels in the status cell are derived: `Voting Open` / `Applications Open` / `Not Started` / `Closed`. | New chrome strings (R4 exception). |
| E11 | Tablet band rules. | D7. |
| E12 | Org brand colours are ignored in this template. | D1. |
| E13 | Sidebar and header use `position: sticky` against **document scroll** (no 800 px frame, no nested scroll). | F14. |
| E15 | Vetting Panel action buttons are lifted to the 44 px floor in Blueprint only (`.vp-actions`, `.vp-switch`). | R10; default stays pixel-identical (R1). |
| E16 | New copy for the any-admin panel link and the vetting close-out (listed in `DEVIATIONS.md`). | R4 exception for new chrome. |

---

## 8. Phase cards

Same format and rules as the runbook cards. IDs are `BP-T0 … BP-T10`; branch `improvements/BP-<ID>` off `integration`; progress note `progress/BP-<ID>.md` (template in §13). **Lanes:** T0 → T1 → T2 → T3 are sequential (T2 and T3 both edit `App.jsx`). After T2, **T4, T5, T6 can run in parallel** (separate files). T7a → T7b are sequential (T7b needs T7a's sidebar). After T7b, **T8a, T8b, T8c can run in parallel** (separate files; `SharedAdminPanels.jsx` belongs to T8a only). T9 and T10 run last, one at a time.

Every card: write the tests first, run only targeted tests while working, run the full suites **twice at the end** (default, then `VITE_UI_TEMPLATE=blueprint`), plus `npm run lint` and **both builds**. Record numbers at the moment the branch is cut ("baseline") and beat them, as in the runbook.

---

#### BP-T0 · Foundations — size S
* **Goal:** the switch, registry, chrome store, test helpers, committed mockup — **no visible change in either template**.
* **FILES:** `src/template.js`, `src/templateChrome.js`, `src/test/template.js`, `src/test/setup.js` (add the env hook), `src/template.test.js`, `src/main.jsx` (activation only), `src/templates/blueprint/index.js` + empty `blueprint.css` (stubs so the dynamic import resolves), `.env.example`, `frontend/.gitignore` (add `dist-blueprint`), `design/blueprint/kes-blueprint-console-mockups.html` (copy of the mockup).
* **Pre-check:** `grep -n "AdminDashboard" src/App.jsx` (expect only a comment → legacy file, out of scope, F17) · `git check-ignore -v frontend/.env.example` must print **nothing** (it must stay tracked) · record baselines: `npm test | tail -5`, `npm run lint | tail -5`, `npx vite build | tail -15` (note entry-chunk gzip KB).
* **Do:** Appendix A code. `setup.js` registers the template when `process.env.VITE_UI_TEMPLATE === 'blueprint'`.
* **Tests:** `resolveTemplate` table (`'blueprint'`→blueprint; `undefined`, `''`, `'default'`, `'Blueprint'`, `' blueprint '`, `'bluprint'` → default) · `setTemplateImpl(m)` sets `html[data-template]`, `setTemplateImpl(null)` removes it · chrome store: `setChrome` notifies once per real change and not on equal patches.
* **Done when:** green; **gate G1** (default build has no blueprint chunk; entry ≤ baseline + 1.5 KB gz).
* **HUMAN:** none.

#### BP-T1 · CSS foundation — size M
* **Goal:** tokens, bridge, base, ported component classes, responsive block, neutraliser fence, print reset — and the tests that guard them. No component changes.
* **FILES:** `src/templates/blueprint/blueprint.css`, `index.js`, `tokens.test.js`, `parity.test.js`, `contrast.test.js`, `scripts/check_template_build.sh`.
* **Pre-check:** `sed -n 1,80p src/index.css` (theme blocks) · `grep -n "data-theme" src/index.css` · the mockup `<style>` block (from `design/blueprint/…`).
* **Do:** Appendices B–C. Keep each section fenced with the comment banners from §4.6.
* **Tests (Appendix D):** token completeness in light, dark and the `prefers-color-scheme` fallback · **drift guard vs the mockup** (every shared token value equal; precomputed tints within ±1 channel of the `color-mix` result) · contrast table (§5.6, incl. D2/D3 rows) · no raw `px` in `padding|margin|gap` · `!important` only inside the fence, one numbered comment per fenced rule · everything visual inside `@media screen` · every mockup class has its `bp-` twin.
* **Done when:** green; `VITE_UI_TEMPLATE=blueprint npx vite build --outDir dist-blueprint` builds; **G2** (blueprint build has the chunk ≤ 30 KB gz). **HUMAN:** with the template on, the **unchanged** login page is legible in light and dark (the bridge alone must be enough for that).

#### BP-T2 · Public shell (header, column, boot) — size M
* **Goal:** the title-block header on every App-shell page; full-width header with a 520 px content column; boot splash in the template's look.
* **FILES:** `src/App.jsx` (seams only), `TitleBlockHeader.jsx` (public variant), `primitives.jsx` (`Stamp`, `initials`, `StatusCell`), `App.template.test.jsx`, `TitleBlockHeader.test.jsx`, `blueprint.css` (neutralisers N2/N3).
* **Pre-check:** `sed -n 706,800p src/App.jsx` · `sed -n 1100,1215p src/App.jsx` · `grep -n "derivePhase\|electionStatus" src/App.jsx`.
* **Do:** replace the `<nav className="no-print" …>` block with `bp ? <bp.TitleBlockHeader …/> : <nav …existing/>`, passing the **same** handlers: `handleVoteNow`, `setView('results'|'apply')`, `toggleTheme`, the Back-to-Admin rule (`adminRole && (view==='results'||view==='apply')`), `orgName`, `logoUrl` (+ `logoNeedsInvert`), `derivePhase(electionStatus)`, voter `step`. Header: brand (stamp: logo image if any, else `initials(orgName)`; title `orgName`; subtitle `Election Portal`), nav with the **existing labels and `data-track`s** (`nav-vote`, `nav-results`, `nav-apply`), status cell (E10), sheet cell (D5), theme toggle. In public views wrap the content in `<div className="bp-wrap">` **only when `bp`** (never an extra div in default). BootSplash: same stages/dots; the ring is replaced by the stamp.
* **Tests:** header shows the same three nav labels with the same `data-track`; active item has `aria-current="page"`; Vote Now still goes through `handleVoteNow` (admin-session confirm preserved); theme toggle flips `data-theme` and localStorage `theme`; Back to Admin only in results/apply with an admin role; status cell text per phase (E10); long org name does not break the header (`title` attribute carries the full name); **default render has no `bp-` class and no `data-template`**.
* **Done when:** green in both modes; G1/G2.
* **HUMAN:** 360, 390, 768, 1280 widths · light/dark · org with no logo / wide logo / tall logo · 200 % zoom · notched iPhone (safe area).

#### BP-T3 · Voter flow — size M
* **Goal:** login, admin-login, resend/links, error modal, phase banner and the OTP screen in the template.
* **FILES:** `src/App.jsx` (step 1/1.5/2 seams), `PhaseBanner.jsx`, `OtpInput.jsx`, `VoterLoginInputs.jsx`, `LoginErrorActions.jsx` (class hooks only), `OtpCells.jsx`, tests `PhaseBanner.template.test.jsx`, `OtpInput.template.test.jsx`, `Login.template.test.jsx`, `blueprint.css`.
* **Pre-check:** `sed -n 812,945p src/App.jsx` · `sed -n 1,60p src/components/VoterLoginInputs.jsx` · `sed -n 1,115p src/components/PhaseBanner.jsx`.
* **Do:** `PhaseBanner`: keep `derivePhase`, countdown logic, `data-phase`, `role="status"`, the single-banner rule and the Apply-now button; only the container classes/colours switch (E2). `OtpInput`: render `OtpCells` **over the one real input** (input stays focusable, `autoComplete`/`inputMode`/paste handling untouched; cells mirror `otp`; the group shows the accent focus ring via `:focus-within`; error → `--bp-no`; locked → 50 %). Fields that only had placeholders get `<label htmlFor>` (reuse the placeholder text). Buttons/links pick up `bp-btn`/`bp-lnk` classes.
* **Tests:** PhaseBanner: 4 states → exactly one `[data-phase]`, Apply-now only for `apply_open` and `data-track="phase-apply-now"`, countdown ticks with fake timers, no hex in the template branch · OtpInput: still **exactly one** `<input>`; typing/paste `"123 456"` → `123456`; cells show digits; `disabled` when `<6`/submitting/locked; lock countdown text and `role="alert"` unchanged; `data-track="otp-submit"` · login: `getByLabelText` finds the fields; `login-submit` label present; admin-path toggle still switches fields.
* **Done when:** green in both modes; existing `PhaseBanner.test`, `LoginErrorActions.test`, `OtpInput.test`, `App.*.test` pass unchanged under `VITE_UI_TEMPLATE=blueprint`.
* **HUMAN:** real phone: SMS autofill fills the code, paste works, keyboard does not hide the Verify button (360×640); screen reader reads one field, not six.

#### BP-T4 · Ballot flow — size M *(parallel after T2)*
* **FILES:** `BallotBox.jsx`, `BottomDock.jsx`, `primitives.jsx` (`StepBar`, `Avatar`), `BallotBox.template.test.jsx`, `blueprint.css`.
* **Pre-check:** `sed -n 170,275p` and `sed -n 285,420p` of `BallotBox.jsx` · `grep -rn "InlineHelpButton\|useReportedHeight" src` (the App comment says the ballot footer hosts Help, but today nothing in `BallotBox` renders `InlineHelpButton`; note the finding in progress, do not "fix" it here).
* **Do:** position headings keep `className="position-header"` **plus** `bp-pos`; candidate rows become `bp-cand` (selected state from the existing `ballot[pos] === id`); initials avatar when there is no image; the dock replaces `footerBarStyle` and publishes its height to `--bottom-bar-height` (the Help FAB already reads it, `HelpTriggers.jsx` ≈ 74 and `HelpPanel.jsx` ≈ 134) and clears it on unmount; review modal and success view restyled by classes/tokens (S2 for the success-check colours).
* **Tests:** toggle select/deselect; dock disabled when empty; label stays `REVIEW & SUBMIT (n)`; `isPreview` hides the dock and shows the preview banner; Clear-All confirm still gates clearing; review countdown still gates submit; `data-track="ballot-submit"`; avatar initials; dock height published/cleared; default render has no `bp-`.
* **Done when:** green in both modes. **HUMAN:** 40+ candidates scroll smoothly; dock never covers the last candidate or the Help button; selected state is visible without colour (tick + outline).

#### BP-T5 · Results — size S–M *(parallel after T2)*
* **FILES:** `Results.jsx`, `primitives.jsx` (`Meter`, `Stat`, `Pill`), `Results.template.test.jsx`, `blueprint.css`.
* **Pre-check:** `sed -n 190,300p src/components/Results.jsx` · `sed -n 425,488p` (banner styles, the hex hotspots) · existing `Results.state.test.jsx`, `resultsState.js`.
* **Do:** the live / provisional / certified banner becomes a stat card + status pill (text unchanged); rows become `bp-meter` (same numbers, same `cand-row` hooks); LEADING/WINNER stay as the existing text in a pill; **do not touch the `print-only` block**.
* **Tests:** each `resultsState` case renders the same text under both templates; bars' `width` equals the percentage; certified shows the certified pill; polling unaffected; print block markup identical in both templates (render both, compare `.print-only` `innerHTML`).
* **Done when:** green. **HUMAN:** print preview of Results identical to default (R8).

#### BP-T6 · Apply form — size M *(parallel after T2)*
* **FILES:** `ApplicantPortal.jsx`, `primitives.jsx` (`StepBar`), `ApplicantPortal.template.test.jsx`, `blueprint.css`.
* **Pre-check:** `sed -n 300,330p`, `sed -n 430,470p`, `sed -n 500,629p` of `ApplicantPortal.jsx` · `grep -n "data-field\|data-track" src/components/ApplicantPortal.jsx`.
* **Do:** form card → `bp-card`; fields → `bp-in` with visible labels (real field names); upload tiles keep their `label`/`data-field`/`tabIndex`; notices → `bp-ban`; `StepBar` bound to the existing `step` and shown only while `uploading`; polling/status views get tokens (Tier B).
* **Tests:** every `data-field` and `data-track` still present; field-error `aria-invalid` still set; submit blocked-state messages unchanged; `StepBar` hidden at `step===0`, shows `step` of 4 during a submit; `ApplicantPortal.apply.test` and `.polling.test` pass in both modes.
* **HUMAN:** photo + payment-proof upload on a phone, slow network note, keyboard open on 360×640.

#### BP-T7a · Console shell, grouped dashboards — size M
* **Goal:** sticky console header (brand · crumb · status · sheet), sidebar rail / mobile pill row, toolbar row — on Super Admin and Commission.
* **FILES:** `TabBar.jsx` (rename → `DefaultTabBar` + wrapper), `AdminHeader.jsx` (same pattern), `ConsoleSidebar.jsx`, `TitleBlockHeader.jsx` (console variant), `App.jsx` (role label + header variant by `view`), `blueprint.css` (neutralisers N5/N6), `ConsoleSidebar.test.jsx`, `AdminHeader.template.test.jsx`.
* **Pre-check:** `grep -n "^export\|^function\|MOBILE_QUERY" src/components/TabBar.jsx` · `sed -n 20,60p src/components/AdminHeader.jsx` · `grep -n "dash-body\|<TabBar\|<AdminHeader" src/components/SuperAdminDashboard.jsx src/components/CommissionDashboard.jsx`.
* **Do:** `ConsoleSidebar` takes the **same props** as `TabBar` (`tabs` | `groups`, `activeTab`, `onChange`), renders `<nav aria-label>` with real `<button>`s (`aria-current="page"`, counts as today), publishes `{ group, tab, tabIndex, tabCount }` to the chrome store. `AdminHeader` (blueprint) keeps title, subtitle, `Sync: …`, `actions`, Refresh, Logout and publishes `onLogout` so the sidebar can add "Session → Log out" (E4). `ConsoleSidebar` in **flat** mode (no frame yet) renders as the horizontal pill row, so T7a is shippable on its own for flat dashboards (just without the rail).
* **Tests:** groups/tabs render from the real arrays (use a fixture mirroring `tabGroups`); click calls `onChange(id)`; `aria-current` follows `activeTab`; counts shown; chrome store receives the crumb; `AdminHeader` buttons by role/name unchanged and `onLogout` called by both Logout controls; role-label mapping (`superadmin`→Super Admin, `commission`→Commission, `it_admin`→IT Admin, `financial_controller`→Financial Controller, `overseer`→Overseer, `vetting`→Vetting Panel).
* **HUMAN:** all groups reachable at 360 px; sidebar scrolls only when taller than the viewport; Logout reachable in ≤ 2 interactions on every viewport.

#### BP-T7b · Flat dashboards frame — size S–M
* **FILES:** `src/components/ConsoleFrame.jsx` (new, **default = passthrough fragment**), `ConsoleFrame.jsx` in `templates/blueprint/`, call sites in `ITAdminDashboard.jsx`, `FinancialControllerDashboard.jsx`, `OverseerDashboard.jsx`, `VettingDashboard.jsx`, test `ConsoleFrame.test.jsx`.
* **Pre-check:** `grep -n "<TabBar" src/components/{ITAdmin,FinancialController,Overseer,Vetting}Dashboard.jsx` · confirm `AdminDashboard.jsx` is untouched (F17).
* **Do:** change `<TabBar …/>{content}` to `<ConsoleFrame nav={<TabBar …/>}>{content}</ConsoleFrame>`. Default: `return <>{nav}{children}</>` (**identical DOM**). Blueprint: `<div className="dash-body">{nav}<div className="dash-main">{children}</div></div>` (reusing the existing 768 px stacking rules).
* **Tests:** default: `container.innerHTML` of a flat dashboard fixture is **byte-identical** before/after the edit (capture the "before" string in the test from a pre-edit snapshot committed with the card); blueprint: nav and content are siblings inside `.dash-body`.
* **HUMAN:** the four dashboards at 1280/768/390.

#### BP-T8a / T8b / T8c · Console content (Tier A) — size M each *(parallel)*
* **T8a Super Admin** — `SuperAdminDashboard.jsx`, `SharedAdminPanels.jsx`, `VoterStats.jsx`, `VoterList.jsx`, `SuperAdminStudentEdit.jsx`, `UsageCharts.jsx`, `HeatmapOverlay.jsx`: mockup pages *SA · Applications / Voters / Student changes / Site usage*.
* **T8b Commission + Overseer** — `CommissionDashboard.jsx`, `OverseerDashboard.jsx`, `TurnoutBreakdown.jsx`, `AlertPanel.jsx`.
* **T8c IT Admin + Finance + Vetting** — `ITAdminDashboard.jsx`, `ITAdminStudentEdit.jsx`, `FinancialControllerDashboard.jsx`, `VettingDashboard.jsx`, `VettingPanelManager.jsx`.
* **Do (all):** stat cards (`bp-stat`), status values as `bp-pill` (**one shared `statusPill(status)` map in `primitives.jsx`**: approved/paid/active → ok; pending/vetting/awaiting → warn; rejected/failed → neg; unpaid/none → mute), result/turnout rows as `bp-meter`, tables with `data-l` cell labels for the mobile card-rows (`bp-table`), alerts as `bp-ban`/`bp-alt`, form fields as `bp-in`, SVG chart colours via S2. **Never remove a control the mockup does not show.**
* **Pre-check each:** `grep -n "style=" <file> | wc -l` and `grep -nE "#[0-9a-fA-F]{3,6}" <file> | head -30` to size the work; list hex literals you leave in `progress/BP-T8x.md` (feeds T9).
* **Tests:** per panel: same rows/columns/values under both templates (render with a fixture, compare `textContent` of table cells); every status maps to exactly one pill class; mobile `data-l` present on every `td`; existing tests pass in both modes.
* **HUMAN:** one real tenant's data in each console, light and dark, desktop and phone.

#### BP-T9 · Tier B sweep — size M
* **Goal:** every remaining screen readable and usable (AA), recorded in the Tier B register.
* **Do:** (1) audit **solid fills** that use `var(--success|--danger|--warning)` (F-note) and give offenders `--bp-ok-solid` etc. via S2; (2) S2 the remaining hotspot hex literals in order of frequency (F9: `#fff`, `#2ecc71`, `#e74c3c`, `#64748b`, `#3b82f6`, `#10b981`, `#e67e22`, `#3498db`); (3) walk the register screen by screen in light/dark/mobile; (4) add a **hex ratchet test**: count of hex literals in non-test `src/**/*.jsx` (excluding `templates/blueprint/` token CSS) must be ≤ the number recorded at the end of this card, so new UI cannot regress.
* **Tests:** ratchet; `rg`-style assertion that no component outside `templates/blueprint/` imports from it statically.
* **HUMAN:** the register's "ok" columns.

#### BP-T10 · Hardening and handover — size M
* **Do:** keyboard walk-through of every Tier A flow; focus ring on every control; `prefers-reduced-motion` (the `.bp-dot` pulse stops); 200 % zoom; print previews (Results, Final Report, certificate) identical to default; size budgets (§4.7); README section "UI templates" in `frontend/README.md`; append the final §13 table to `DEVIATIONS.md`.
* **Done when:** §13 acceptance list all ticked.

---

## 9. Test plan

| Layer | What | How |
|---|---|---|
| **L1 Resolver / registry** | strict switch, registry sets/clears `data-template` | `src/template.test.js` (T0) |
| **L2 Static design tests** (no DOM) | token completeness, **drift vs mockup**, contrast, spacing scale, `!important` fence, `@media screen` fence, class parity | `tokens.test.js`, `parity.test.js`, `contrast.test.js` (T1) — Appendix D |
| **L3a Default regression** | with the template off: no `data-template`, no `[class*="bp-"]`, DOM of seam-wrapped components unchanged | `beforeEach(useDefault)` / `afterEach(restoreTemplate)` in every `*.template.test.jsx` |
| **L3b Behaviour parity net** | **the entire existing suite with the template on** | `VITE_UI_TEMPLATE=blueprint npm test`. Failures are bugs in the blueprint, or must be listed in §7 |
| **L4 Template render tests** | structure, labels, `data-track`, states, handlers per Tier A component | per-card tests above, using `useBlueprint()` |
| **L5 Build gates** | (a) nothing outside `templates/blueprint/` imports it statically; (b) default build has no blueprint chunk and no `bp-` strings; (c) size budgets; (d) `scripts/check_data_track.py` still prints OK | `scripts/check_template_build.sh` (§10) |
| **L6 Visual parity (manual, deterministic)** | side-by-side with the mockup deep links | §12 |
| **L7 Device / environment (manual)** | real phones, slow network, print, zoom, keyboard, screen reader | §12 |
| **L8 Ratchet** | hex-literal count may only go down | T9 test |

**What L3b buys you.** Existing tests find things by role, name and text (F11) and the copy is frozen (R4), so they exercise every handler and state machine through the *blueprint* markup. That is the cheapest strong proof that the template changed the look and nothing else.

**Test helper pattern** (Appendix A has the code): a test either calls `useDefault()` (to prove the default path) or `useBlueprint()`; `afterEach(restoreTemplate)` returns to whatever the run's environment says, so both `npm test` and `VITE_UI_TEMPLATE=blueprint npm test` stay meaningful.

**What jsdom cannot prove** (CSS is not applied, there is no layout): target sizes, sticky/overflow behaviour, wrapping, safe-area. Those are covered by the static CSS assertions in L2 (e.g. `.bp-btn { min-height: var(--bp-tap) }`) and by §12.

---

## 10. Gates (copy-paste)

```bash
# from frontend/ — run at the end of every card
npm test | tail -5
VITE_UI_TEMPLATE=blueprint npm test | tail -5          # L3b
npm run lint | tail -5
bash scripts/check_template_build.sh                  # G1 + G2 (Appendix E)
python ../frontend/scripts/check_data_track.py        # run from the repo root as today: python frontend/scripts/check_data_track.py
```

| Gate | Pass condition |
|---|---|
| **G1 default build** | no `dist/assets/*blueprint*`; `grep -l "bp-" dist/assets/*.js` finds nothing; entry chunk gzip ≤ baseline + 1.5 KB |
| **G2 blueprint build** | `dist-blueprint` has a blueprint JS + CSS chunk, total ≤ 30 KB gzip; entry ≤ default + 2 KB gzip |
| **G3 parity** | `VITE_UI_TEMPLATE=blueprint npm test` = same pass count as default + the new template tests |
| **G4 data-track** | script prints `data-track labels OK` |
| **G5 lint** | 0 errors, 0 warnings (the R12 wrapper pattern keeps `react-hooks` quiet) |

---

## 11. Rollout and rollback

1. Merge all cards to `integration` with the variable **unset** everywhere → production behaviour unchanged (G1 proves it).
2. Create a **Vercel Preview** for one tenant with `VITE_UI_TEMPLATE=blueprint`; run the §12 matrix.
3. Turn it on **tenant by tenant** (Production env var, redeploy). Do **not** switch during an election window.
4. **Rollback:** delete the variable (or set it empty) and redeploy. No data, backend, session or storage migration exists, so rollback is instant. A user who loaded the old bundle keeps working (API unchanged).
5. If the blueprint chunk ever fails to load for a user, the app falls back to the default UI (§4.3).

---

## 12. HUMAN checklist (no AI can do these)

* **Mockup deep links** make side-by-side checks deterministic. Open the committed mockup with `#t=<light|dark>&v=<desktop|mobile>&p=<page>&g=<0|1>` — pages: `spec, boot, login, otp, ballot, review, done, results, apply, sa, voters, chg, usage, it, com, fin, vet, ov`; `g=1` overlays the 8 px rhythm and labels for header/outer/cell/gutter sizes. Compare each against the running app at **1280×800** and **390×800**, light and dark: **18 pages × 4 variants**.
* **Per Tier A screen:** header height/margins/dashed dividers/ruler edge · card top border and padding · field heights (48) · button shape · pill colours · spacing steps (no off-scale padding) · nothing clipped or horizontally scrolling.
* **Devices:** low-end Android on Slow 3G (blueprint chunk size, no flash of the wrong design, OTP autofill/paste, vote with network dropped); an iPhone with a notch (safe areas, dock above the home bar); a tablet at 800–1000 px (D7).
* **Content stress:** org with a very long name; wide, tall and missing logo; 40+ candidates; very long reg numbers/emails in tables; 200 % browser zoom.
* **Accessibility:** keyboard-only through login → vote → results and one console; screen reader pass on login, OTP, ballot; reduced-motion setting on.
* **Print:** Results, Final Report and the certificate print identically in both templates (compare PDFs).
* **Tier B register** columns "ok" for every row.
* **Brand decision D1:** show the owner a tenant with a strongly coloured brand in the blueprint look.

---

## 13. Final acceptance and progress template

**Acceptance (all must be true):**
- [ ] Default build: G1 passes; default suite = baseline + new tests; lint 0/0.
- [ ] `VITE_UI_TEMPLATE=blueprint npm test` passes (G3); G2, G4 pass.
- [ ] §5.6 contrast and D2/D3 rules enforced by tests; token drift test green against the committed mockup.
- [ ] Every Tier A screen in §6.1 checked against its mockup deep link in both themes and both viewports.
- [ ] Tier B register complete; hex ratchet recorded.
- [ ] §7 deviations reviewed and accepted by the owner (D1–D9 answered).
- [ ] Print previews identical; HUMAN device checks done.
- [ ] `frontend/README.md` "UI templates" section; `.env.example` documents `VITE_UI_TEMPLATE`.

`progress/BP-<ID>.md` — the runbook §6 template plus two lines:
```markdown
# BP-<ID> — <title>
status: done | partial | blocked
branch: improvements/BP-<ID>
commits: <sha> <message>
tests added: <files and count>
results (default):   frontend <N passed, M failed> · lint <e/w> · build <ok/fail, entry gz KB>
results (blueprint): frontend <N passed, M failed> · build <ok/fail, entry gz KB, blueprint chunk gz KB>
baseline at branch cut: frontend <N> · entry gz <KB>
deviations: <none | list, or see deviations/BP-<ID>.md>
HUMAN checks pending: <list or none>
next step (only if partial): <exact file and action>
```

**Backlog (not part of v1):** B1 org-accent theming with a contrast-gated derivation (flip D1) · B2 promote Tier B panels to individual cards · B3 optional dev-only Guides overlay (`?bpguides=1`) ported from the mockup · B4 `/status/<token>` and `/verify/<id>` header (D9).

---

# Appendices (reference code — not executed when this guide was written; the gates verify it)

## Appendix A — registry, chrome store, test helpers

```js
// src/template.js
export const UI_TEMPLATES = ['default', 'blueprint'];
export const resolveTemplate = (raw) => (raw === 'blueprint' ? 'blueprint' : 'default');
export const UI_TEMPLATE = resolveTemplate(import.meta.env.VITE_UI_TEMPLATE);

let impl = null;                                   // null => the standard UI
export function setTemplateImpl(mod) {
  impl = mod || null;
  if (typeof document !== 'undefined') {
    if (impl) document.documentElement.dataset.template = 'blueprint';
    else delete document.documentElement.dataset.template;
  }
}
export const getTemplate = () => impl;             // call at render time, never at import time
```

```js
// src/templateChrome.js — header <-> dashboard handshake (tiny, always bundled)
import { useSyncExternalStore } from 'react';
const EMPTY = { role: '', group: '', tab: '', tabIndex: 0, tabCount: 0, onLogout: null };
let state = EMPTY;
const subs = new Set();
export function setChrome(patch) {
  if (Object.keys(patch).every((k) => Object.is(state[k], patch[k]))) return;   // no churn
  state = { ...state, ...patch };
  subs.forEach((f) => f());
}
export const resetChrome = () => setChrome(EMPTY);
export const useChrome = () => useSyncExternalStore(
  (f) => { subs.add(f); return () => subs.delete(f); },
  () => state,
);
```

```js
// src/test/template.js
import { setTemplateImpl } from '../template';
const ENV_BP = process.env.VITE_UI_TEMPLATE === 'blueprint';
let mod;
const load = async () => (mod ??= await import('../templates/blueprint/index.js'));
export async function useBlueprint() { setTemplateImpl(await load()); }
export function useDefault() { setTemplateImpl(null); }
export async function restoreTemplate() { return ENV_BP ? useBlueprint() : useDefault(); }
export const envIsBlueprint = ENV_BP;
```

```js
// src/test/setup.js  (add below the existing import)
import { useBlueprint, envIsBlueprint } from './template';
if (envIsBlueprint) await useBlueprint();
```

```js
// pattern inside a *.template.test.jsx
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';
afterEach(restoreTemplate);
it('default render has no blueprint markup', () => {
  useDefault();
  const { container } = render(<PhaseBanner status={S.voting_open} />);
  expect(document.documentElement.dataset.template).toBeUndefined();
  expect(container.querySelector('[class*="bp-"]')).toBeNull();
});
it('blueprint render keeps data-phase', async () => {
  await useBlueprint();
  const { container } = render(<PhaseBanner status={S.voting_open} />);
  expect(container.querySelectorAll('[data-phase]')).toHaveLength(1);
});
```

## Appendix B — `blueprint.css` skeleton: tokens, bridge, fence

```css
/* ===== 1. TOKENS ===== values must equal the mockup (parity.test.js) */
html[data-template="blueprint"] {
  --bp-s1:4px; --bp-s2:8px; --bp-s3:12px; --bp-s4:16px; --bp-s5:24px; --bp-s6:32px; --bp-s7:48px;
  --bp-gut:var(--bp-s5); --bp-pad:var(--bp-s5); --bp-hh:64px; --bp-tap:48px; --bp-r:12px; --bp-rs:8px;
  --bp-fm:ui-monospace,Menlo,Consolas,monospace; --bp-fh:var(--bp-fm);
}
html[data-template="blueprint"]:not([data-theme]),
html[data-template="blueprint"][data-theme="light"] {
  --bp-bg:#e9ecef; --bp-sf:#fff; --bp-sf2:#f1f3f5; --bp-sf3:#fff;
  --bp-line:#ced4da; --bp-line-ui:#7c8696;
  --bp-tx:#14213d; --bp-mu:#5c677d; --bp-ac:#c2410c; --bp-ai:#fff;
  --bp-ok:#1b6e2f; --bp-wn:#8f4d00; --bp-no:#b42323;
  --bp-grid:rgba(20,33,61,.06); --bp-sh:0 8px 24px rgba(11,37,69,.10);
  --bp-tint:#f9ece7; --bp-tint2:#f4ddd3;
  --bp-ok-tint:#e8f0ea; --bp-wn-tint:#f4ede6; --bp-no-tint:#f8e9e9; --bp-mu-tint:#eff0f2;
}
html[data-template="blueprint"][data-theme="dark"] {
  --bp-bg:#0b2545; --bp-sf:#10335f; --bp-sf2:#0d2b52; --bp-sf3:#143b6e;
  --bp-line:#2b4f80; --bp-line-ui:#6f90bd;
  --bp-tx:#e8f0fb; --bp-mu:#a3b8d4; --bp-ac:#ff922b; --bp-ai:#0b2545;
  --bp-ok:#69db7c; --bp-wn:#ffc078; --bp-no:#ffa3a3;
  --bp-grid:rgba(255,255,255,.05); --bp-sh:0 8px 24px rgba(0,0,0,.35);
  --bp-tint:#283c5a; --bp-tint2:#3b4456;
  --bp-ok-tint:#194462; --bp-wn-tint:#284162; --bp-no-tint:#283e66; --bp-mu-tint:#1f406b;
}
@media (prefers-color-scheme: dark) {      /* before App sets data-theme; same values as the dark block */
  html[data-template="blueprint"]:not([data-theme]) { /* …repeat the dark declarations… */ }
}
@media (max-width: 768px) {
  html[data-template="blueprint"] { --bp-gut:var(--bp-s4); --bp-pad:var(--bp-s4); --bp-hh:56px; }
}

/* ===== 2. BRIDGE (S1) — existing variables follow the template ===== */
html[data-template="blueprint"] {
  --bg-color:var(--bp-bg); --card-bg:var(--bp-sf); --surface-2:var(--bp-sf2);
  --border-color:var(--bp-line); --text-color:var(--bp-tx); --text-muted:var(--bp-mu);
  --success:var(--bp-ok); --danger:var(--bp-no); --warning:var(--bp-wn); --info:var(--bp-ac);
}
@media screen {
  html[data-template="blueprint"] body {
    background-color:var(--bp-bg);
    background-image:linear-gradient(var(--bp-grid) 1px,transparent 1px),linear-gradient(90deg,var(--bp-grid) 1px,transparent 1px);
    background-size:24px 24px; background-attachment:fixed;
  }
  /* ===== 3. BASE · 4. COMPONENTS · 5. RESPONSIVE — port per Appendix C ===== */
  /* ===== NEUTRALISERS ===== */
  /* N1 App.jsx:~316 — org branding is written inline on <html>; pin the template's accent (D1) */
  html[data-template="blueprint"] { --brand-primary:var(--bp-ac) !important; --brand-accent:var(--bp-ac) !important; }
  /* N2 App.jsx:~1187 containerStyle — 20px padding, centred, 100vh */
  html[data-template="blueprint"] .app-shell { padding:0 !important; justify-content:flex-start !important; }
  /* N3 App.jsx:~735 inline maxWidth 500px — header is full width; .bp-wrap centres content at 520 */
  html[data-template="blueprint"] .app-column { max-width:100% !important; }
  /* N5 each dashboard's outerWrap const — inline padding */
  html[data-template="blueprint"] .outer-wrap { padding:0 !important; }
  /* N6 each dashboard's container const — content pane becomes the mockup card (D4) */
  html[data-template="blueprint"] .dashboard-shell {
    background:var(--bp-sf) !important; border:1px solid var(--bp-line) !important;
    border-top:3px solid var(--bp-ac) !important; border-radius:var(--bp-r) !important;
    box-shadow:var(--bp-sh) !important; padding:var(--bp-pad) !important;
  }
  /* …N7+ : modals (inline radius 20px), shared input/select/textarea shape, shared button shape… */
  /* ===== /NEUTRALISERS ===== */
}
@media print {
  html[data-template="blueprint"] body { background-image:none !important; }   /* the only !important outside the fence: print reset */
}
```
> The print reset's `!important` is the one allowed exception; the fence test whitelists it by its `@media print` parent.

## Appendix C — porting the mockup CSS mechanically

1. Copy the mockup's `<style>` block. **Delete tooling:** `.tb*`, `#st`, `#sc`, `.dev` frame (`height`, `overflow:hidden`, `border-radius:16px`), `.gd*` (Guides), `.sp`, `.sw`, the fixed 800 px device frame.
2. Replace `.dev[data-t=light|dark]{…}` and the `.dev{--s1…}` block with Appendix B's tokens. Rename every variable `--x` → `--bp-x` (mockup `--tint/--tint2` become the precomputed values; delete every `color-mix(...)` — status tints use the `--bp-*-tint` tokens, pill/banner edges use `rgb(r g b / .35)` literals **inside the token block only**).
3. The `.dev` grid background moves to `body` (Appendix B).
4. **Rename classes** with the `bp-` prefix, **modifiers too**:

```js
export const RENAME = {
  top:'bp-top', tl:'bp-tl', logo:'bp-logo', bt:'bp-bt', crumb:'bp-crumb', cell:'bp-cell', dot:'bp-dot', rule:'bp-rule',
  wrap:'bp-wrap', wide:'bp-wide', card:'bp-card', in:'bp-in', f:'bp-focus', btn:'bp-btn', g:'bp-ghost', sm:'bp-sm',
  lnk:'bp-lnk', ban:'bp-ban', w:'bp-warn', alt:'bp-alt', pos:'bp-pos', cand:'bp-cand', av:'bp-av', tick:'bp-tick',
  on:'bp-on', dock:'bp-dock', big:'bp-big', stat:'bp-stat', pill:'bp-pill', n:'bp-neg', m:'bp-mute', row:'bp-meter',
  t:'bp-t', bar:'bp-bar', shell:'bp-shell', side:'bp-side', brand:'bp-brand', main:'bp-main', grid:'bp-grid',
  g2:'bp-g2', g4:'bp-g4', k:'bp-k2', rs:'bp-rs', cen:'bp-cen', otp:'bp-otp', steps:'bp-steps', chart:'bp-chart',
  hot:'bp-hot', two:'bp-two', chip:'bp-chip', lg:'bp-lg', sh:'bp-sheet', st:'bp-status', ov:'bp-ov', sc:'bp-sc',
  mu:'bp-mu', num:'bp-num', mono:'bp-mono',
};
// Tooling classes that are NOT ported (the parity test ignores them):
export const TOOLING = ['tb','dev','gd','sp','sw'];
```
   `.top nav` → `.bp-nav`; element selectors that must reach existing markup (`label`, `input`, `table`, `th`, `td`, `h1–h3`) are scoped `html[data-template="blueprint"] .dashboard-shell …` / `.app-column …` and wrapped in `@media screen`.
5. **`.m …` → `@media (max-width:768px){ … }`** (drop the `.m` prefix; keep the rule bodies). Add the tablet band (D7) next to it.
6. **Scroll model:** remove the mockup's internal scrolling (`.sc{overflow:auto;flex:1}`, `.main{overflow:auto}`, `#st`). `.bp-top` stays `position:sticky; top:env(safe-area-inset-top,0px)`. `.bp-side` becomes `position:sticky; top:calc(var(--bp-hh) + var(--bp-s5)); max-height:calc(100dvh - var(--bp-hh) - var(--bp-s6)); overflow:auto` (the only scroll axis, same idea as the existing `.tabbar-rail`). On mobile the pill row scrolls horizontally like the existing `.tab-scroll`.
7. **Dock:** `position:fixed; left:var(--bp-gut); right:var(--bp-gut); bottom:calc(var(--bp-s3) + env(safe-area-inset-bottom,0px)); max-width:520px; margin:0 auto`; ballot content keeps ≥ 120 px bottom padding (as today).
8. **Spacing:** every `padding|margin|gap` value uses `var(--bp-s*)`/`var(--bp-gut)`/`var(--bp-pad)` or `0` (tested). Component sizes (40, 48, 56, 72 px) are named constants in the file's header comment.
9. **Never** set a colour from a literal; use tokens (R6). **Never** style `h1–h3` outside `@media screen` (print uses its own fonts).
10. Keep `:where(button,a,input,select,textarea):focus-visible{outline:2px solid var(--bp-ac); outline-offset:2px}` (accent on `sf` = 5.18 / 5.66).

## Appendix D — static test sketches (`tokens.test.js`, `parity.test.js`, `contrast.test.js`)

```js
import { readFileSync } from 'node:fs';
import { describe, it, expect } from 'vitest';

const css = readFileSync(new URL('./blueprint.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const mock = readFileSync(new URL('../../../design/blueprint/kes-blueprint-console-mockups.html', import.meta.url), 'utf8');

const rules = (src) => [...src.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, sel, body]) => ({ sel: sel.trim(), body }));
const vars = (body) => Object.fromEntries([...body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)].map(([, k, v]) => [k, v.trim()]));
const themeVars = (name) => Object.assign({}, ...rules(css).filter((r) => r.sel.includes(`[data-theme="${name}"]`)).map((r) => vars(r.body)));
const mockVars = (name) => vars(mock.match(new RegExp(`\\.dev\\[data-t=${name}\\]\\{([^}]*)\\}`))[1]);

const REQUIRED = ['bg','sf','sf2','sf3','line','line-ui','tx','mu','ac','ai','ok','wn','no','grid','sh','tint','tint2','ok-tint','wn-tint','no-tint','mu-tint'];
const SHARED   = ['bg','sf','sf2','sf3','line','tx','mu','ac','ai','ok','wn','no','grid'];   // exist in the mockup under the same name (minus --bp-)

for (const theme of ['light', 'dark']) {
  describe(`tokens (${theme})`, () => {
    const t = themeVars(theme), m = mockVars(theme);
    it('defines every required token', () => { for (const k of REQUIRED) expect(t[`bp-${k}`], k).toBeTruthy(); });
    it('matches the mockup values (drift guard)', () => { for (const k of SHARED) expect(t[`bp-${k}`].replace(/\s/g,''), k).toBe(m[k].replace(/\s/g,'')); });
    it('precomputed tints equal the mockup color-mix result (±1/channel)', () => {
      const mix = (a, b, p) => [0, 2, 4].map((i) => Math.round(parseInt(a.slice(1 + i, 3 + i), 16) * p + parseInt(b.slice(1 + i, 3 + i), 16) * (1 - p)));
      const close = (hex, rgb) => [0, 2, 4].every((i, j) => Math.abs(parseInt(hex.slice(1 + i, 3 + i), 16) - rgb[j]) <= 1);
      expect(close(t['bp-tint'],  mix(t['bp-ac'], t['bp-sf'], .10))).toBe(true);
      expect(close(t['bp-tint2'], mix(t['bp-ac'], t['bp-sf'], .18))).toBe(true);
      for (const k of ['ok', 'wn', 'no', 'mu']) expect(close(t[`bp-${k}-tint`], mix(t[`bp-${k}`], t['bp-sf'], .10)), k).toBe(true);
    });
  });
}

// contrast.test.js — WCAG relative luminance
const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const lum = (h) => { const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

for (const theme of ['light', 'dark']) {
  it(`contrast (${theme})`, () => {
    const t = Object.fromEntries(Object.entries(themeVars(theme)).map(([k, v]) => [k.replace('bp-', ''), v]));
    const TEXT = [['tx','sf'],['tx','bg'],['mu','sf'],['mu','bg'],['mu','sf2'],['mu','sf3'],['ai','ac'],['ac','sf'],['ac','sf2'],['ac','sf3'],
                  ['ok','ok-tint'],['wn','wn-tint'],['no','no-tint'],['mu','mu-tint'],['ok','sf'],['wn','sf'],['no','sf'],['tx','tint'],['tx','tint2']];
    for (const [fg, bg] of TEXT) expect(ratio(t[fg], t[bg]), `${fg}/${bg}`).toBeGreaterThanOrEqual(4.5);
    for (const s of ['sf', 'sf2', 'sf3']) expect(ratio(t['line-ui'], t[s]), `line-ui/${s}`).toBeGreaterThanOrEqual(3);   // D2
    // D3 is a usage rule: accent text only on card surfaces. Known light-mode non-text-safe pairs, asserted so nobody "fixes" them by accident:
    if (theme === 'light') { expect(ratio(t.ac, t.bg)).toBeLessThan(4.5); expect(ratio(t.ac, t.tint)).toBeLessThan(4.5); }
  });
}

// tokens.test.js — structural rules
it('no raw px in padding/margin/gap', () => {
  const bad = [...css.matchAll(/(?:padding|margin|gap|row-gap|column-gap)[\w-]*\s*:\s*([^;}]+)/g)].filter(([, v]) => /(?<![\w.-])[1-9]\d*(?:\.\d+)?px/.test(v));
  expect(bad.map((m) => m[0])).toEqual([]);
});
it('!important only inside the NEUTRALISERS fence (plus the print reset)', () => {
  const raw = readFileSync(new URL('./blueprint.css', import.meta.url), 'utf8');
  const [before, rest] = raw.split('/* ===== NEUTRALISERS ===== */');
  const [fence, after] = rest.split('/* ===== /NEUTRALISERS ===== */');
  const strip = (s) => s.replace(/@media print[\s\S]*$/, '');
  expect(strip(before + after)).not.toMatch(/!important/);
  const rulesInFence = (fence.match(/\{[^{}]*\}/g) || []).length;
  expect((fence.match(/\/\* N\d+ /g) || []).length).toBe(rulesInFence);          // one numbered "what it beats" comment per rule
});
it('all visual CSS is screen-only', () => {               // top level = token rules, @media screen/print/prefers-color-scheme/max-width token overrides
  let depth = 0, cur = '', tops = [];
  for (const ch of css) { if (ch === '{') { if (!depth) tops.push(cur.trim()); depth++; cur = ''; } else if (ch === '}') { depth--; cur = ''; } else if (!depth) cur += ch; }
  const ok = (p) => p.startsWith('@media screen') || p.startsWith('@media print') || p.startsWith('@media (prefers-color-scheme') || p.startsWith('@media (max-width') || p.startsWith('html[data-template="blueprint"]');
  expect(tops.filter((p) => p && !ok(p))).toEqual([]);
});
// parity.test.js — every mockup class has its bp- twin
it('class parity with the mockup', async () => {
  const { RENAME, TOOLING } = await import('./rename.js');               // Appendix C table, kept as a module
  const style = mock.match(/<style>([\s\S]*?)<\/style>/)[1];
  const used = [...new Set([...style.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]))].filter((c) => !TOOLING.includes(c));
  const missing = used.filter((c) => !new RegExp(`\\.${RENAME[c] ?? 'bp-' + c}(?![\\w-])`).test(css));
  expect(missing).toEqual([]);
});
```
(Adapt the regexes to the real file as you port; if a test is too strict for a legitimate construct, change the test **and say why** in `progress/BP-T1.md`.)

## Appendix E — `scripts/check_template_build.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
gz() { gzip -c "$1" | wc -c; }                       # bytes, gzipped

echo "== G1: default build =="
rm -rf dist && npx vite build >/dev/null
ls dist/assets | grep -i blueprint && { echo "FAIL: blueprint chunk in default build"; exit 1; } || true
grep -l "bp-" dist/assets/*.js >/dev/null 2>&1 && { echo "FAIL: bp- strings in default JS"; exit 1; } || true
ENTRY=$(ls dist/assets/index-*.js | head -1); D=$(gz "$ENTRY"); echo "default entry gz: $D bytes"
[ -n "${BASELINE_ENTRY_GZ:-}" ] && [ "$D" -gt $((BASELINE_ENTRY_GZ + 1536)) ] && { echo "FAIL: entry grew > 1.5 KB"; exit 1; } || true

echo "== G2: blueprint build =="
rm -rf dist-blueprint && VITE_UI_TEMPLATE=blueprint npx vite build --outDir dist-blueprint >/dev/null
BP=$(ls dist-blueprint/assets | grep -i -E "blueprint|templates" || true); [ -n "$BP" ] || { echo "FAIL: no blueprint chunk"; exit 1; }
TOTAL=0; for f in $(find dist-blueprint/assets -type f \( -name '*lueprint*.js' -o -name '*lueprint*.css' \)); do TOTAL=$((TOTAL + $(gz "$f"))); done
echo "blueprint chunk gz: $TOTAL bytes"; [ "$TOTAL" -le 30720 ] || { echo "FAIL: blueprint chunk > 30 KB gz"; exit 1; }
E2=$(ls dist-blueprint/assets/index-*.js | head -1); echo "blueprint entry gz: $(gz "$E2") bytes (budget: default + 2048)"
echo "OK"
```
Run once at branch cut with `BASELINE_ENTRY_GZ=<bytes>` unset to record the number, then pass it in for later cards. If Vite names the chunk differently, adjust the two `grep`/`find` name patterns — the **assertions** (absent in default, present and small in blueprint) are what matter.
