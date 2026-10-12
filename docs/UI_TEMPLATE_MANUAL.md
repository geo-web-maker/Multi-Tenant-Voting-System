# BallotBox UI Template Manual

How to add or change a screen so it looks right in **both** templates. Read this before touching any front-end page. It sits beside `BLUEPRINT_TEMPLATE_GUIDE.md` (the Blueprint design spec and card history); this file is the day-to-day rulebook.

## 1. The two templates

| | Default | Blueprint Console |
|---|---|---|
| Switch | `VITE_UI_TEMPLATE` unset or empty | `VITE_UI_TEMPLATE=blueprint` (build time, one value per deployment) |
| Styles | `frontend/src/index.css` | `frontend/src/templates/blueprint/blueprint.css` (loaded only in Blueprint builds) |
| Components | the normal components | `frontend/src/templates/blueprint/*.jsx`, chosen at render time with `getTemplate()` |

There is exactly **one** Blueprint stylesheet: `src/templates/blueprint/blueprint.css`. Never create another copy (an unused `src/blueprint.css` once drifted from it and tests read the wrong file).

## 2. The golden rule

**New panels are written once, with the shared panel kit (section 3), and contain no template branches.** The kit's classes exist in `index.css` for the default look; `blueprint.css` re-tones the same classes. A page that uses only kit classes looks correct in both templates without extra work.

Branch on `getTemplate()` only for something structurally different (header, sidebar, OTP cells, status pill). If you need a branch inside a normal admin panel, first ask whether the kit is missing a class.

## 3. The panel kit (use these, do not invent)

Defined in `index.css` (search "Performance tab" and "Shared panel kit"), re-toned in `blueprint.css` between `===== PANEL KIT` and `===== /PANEL KIT`.

| Need | Class | Notes |
|---|---|---|
| Card / panel | `perf-card card-pad` on a `<section>` | 12 px radius, 16 px padding. In Blueprint it is a plain bordered panel: the console shell is already the accent-topped card, so **never nest `bp-card` inside a dashboard panel**. |
| Panel title | `<h3 style={{ margin: '0 0 6px', fontSize: 15 }}>` | Blueprint makes it mono uppercase automatically. |
| Description line | `perf-lead` (under a title), `perf-note` (small hint) | muted text |
| Tile inside a card | `perf-card card-pad perf-tile` (+ `perf-tile-label`, `perf-tile-sub`) | same surface as the card in both templates |
| Button | `perf-btn` | 44 px (48 px in Blueprint), pill in Blueprint |
| Primary / selected | `perf-btn perf-btn-primary`, or `aria-selected` / `aria-pressed` on `perf-btn` | text colour is chosen for contrast on the accent |
| Destructive | `perf-btn perf-btn-danger` | |
| File picker | `<label className="perf-btn">` with a hidden input | |
| Row of buttons | `perf-btnbar` (add `perf-btnbar-stack` to stack full width on phones) | **Not** `perf-bar`: that is the progress bar. |
| Field | `perf-field` on `input`, `select`, `textarea` | 48 px, 16 px text so iOS does not zoom |
| Tick / radio row | `perf-check` (group in `perf-checks`) | |
| Label + value + action strip | `perf-row` with `perf-row-title`, `perf-row-text`, and a trailing `perf-btn` | the button moves right automatically |
| Status message | `perf-msg` with `data-kind="ok"` or `"error"` | never colour alone: the text says what happened |
| Status pill | `BackupPill` / `<bp.Pill>` | always renders the word (Healthy, Failed...) |
| Checklists, key-value, chips | `perf-checklist`, `perf-kv`, `perf-chips` (see `BackupUI.jsx`) | |

Cards and tiles for Backups come from `cardClass()` / `tileClass()` in `BackupUI.jsx`; use those there.

## 4. Adding a new panel: checklist

1. Build it with the kit classes above. No hex colours, no new fonts, no new dependencies.
2. Colours: only `var(--...)` tokens (`--text-muted`, `--border-color`, `--card-bg`, `--success`, `--danger`...). If you need a new colour, add a token, never a literal.
3. Every control is at least 44 px tall (kit classes already do this). Fields use `perf-field`.
4. Keep all existing copy rules: formal wording, proper capitals.
5. Do not change API calls, storage keys, `data-track`, ids or `data-phase` as part of a visual change.
6. Add the tab in the dashboard's tab array (`SuperAdminDashboard.jsx` `tabGroups`, or the role's own list). Blueprint's sidebar reads those arrays; do not hard-code navigation.
7. Wrap long-running or polled data in the existing helpers (`usePolling`, `LoadingBlock`) like the Performance and Backups pages.
8. Phone check (390 px): no sideways scroll, buttons stack, nothing squeezed to one side.

## 5. Changing the look of the kit

- A look change to default goes in `index.css`; the matching Blueprint change goes in the `PANEL KIT` block. Change both in the same commit, or one template drifts.
- Blueprint rules are written as `html[data-template="blueprint"] .perf-...`, inside `@media screen`, with **no `!important`** except inside the fenced `NEUTRALISERS` section (each with a comment naming the inline style it beats).
- Blueprint colours come from `--bp-*` tokens only. Accent-coloured *text* only on card surfaces; selected buttons use `--bp-ai` ink on `--bp-ac`.
- Print must not change: keep visual Blueprint rules out of `@media print`.

## 6. Pitfalls we have already hit

- **Class name collisions.** `perf-bar` is the progress bar; a button row named the same collapsed into a thin grey bar. Search `index.css` and `blueprint.css` for a class before using a new one.
- **Nested cards.** Using `bp.cls.card` inside a dashboard panel gives a second accent top border, shadow and margin.
- **`bp.cls.alt` is the red error block.** Never use it as a neutral surface.
- **A `<label>` styled as a button** picks up Blueprint's mono uppercase label look; the kit has a rule for `label.perf-btn`, so use that class.
- **Inline styles beat classes.** A hand-written inline `background` or `border` on a panel will ignore Blueprint. Prefer a class.
- **Hooks.** A template wrapper must not early-return inside a component that uses hooks; rename the old component and export a thin chooser (guide section 4.5).
- **Two stylesheets.** Edit only `src/templates/blueprint/blueprint.css`.

## 7. Verifying a change

Run all of these before calling a card done:

```bash
cd frontend
npx vitest run                              # default template
VITE_UI_TEMPLATE=blueprint npx vitest run   # the whole suite again, Blueprint on
npx vite build --outDir /tmp/dist-default
VITE_UI_TEMPLATE=blueprint npx vite build --outDir /tmp/dist-bp
ls /tmp/dist-default/assets | grep -i blueprint   # must print nothing
```

Then look at the page by eye, in both templates, light and dark, at ~1100 px and 390 px. Tests do not catch an ugly layout.

Tests that pin template structure, and what they guard:

| Test | Guards |
|---|---|
| `components/BackupUI.template.test.jsx` | kit classes in both templates, one `PANEL KIT` block, no stale second stylesheet |
| `components/BackupChecklist.test.jsx` | checklist classes exist in both stylesheets |
| `perfTapTargets.test.js` | 44/48 px targets, no `!important` in perf rules |
| `components/ConsoleT8b.template.test.jsx` | Alerts and turnout panels per template |
| `templates/blueprint/*.test.js` | tokens, contrast, parity of mockup classes |

| `uiTemplateRules.test.js` | the manual's rules as ratchets: one Blueprint stylesheet, kit panels stay kit-only, only Tier A files use the Blueprint card, no new file invents button styles, every `perf-*` class is defined |

If you rename a kit class or marker comment, update these tests in the same change. When you migrate a file off its own button styles, delete it from `LEGACY_BUTTON_FILES` in `uiTemplateRules.test.js` (the test fails on stale entries).

## 8. Recording the work

One card per session. Write `progress/<card>.md` (what changed, what you ran, what you did not run). Any deliberate departure from this manual or the guide goes in `docs/DEVIATIONS.md` with the reason. Provide a forward patch; a reverse (remove) patch only when asked.

## 9. Open items (updated 12 October 2026)

- The priority admin-panel migration is now applied to the working tree: 162 button/style usages across the listed admin dashboards and small panels use the shared `perf-btn` kit; the migrated files were removed from `LEGACY_BUTTON_FILES`. Remaining allow-list entries are Tier A voter/applicant flows, public/export/utility flows with bespoke interaction needs, or small text-link controls. Their rationale is recorded in `progress/UI-BUTTONS-REMAINDER.md` and `docs/DEVIATIONS.md`.
- `PerformanceSettings.jsx` no longer repeats the `.perf-field` inline style.
- `BackupUI.jsx` contains React components only; pure formatting/status helpers live in `BackupUtils.js` to avoid `react-refresh/only-export-components` warnings.
- Automated frontend tests, lint and both builds still need to be run in an environment with the project dependencies installed. Real browser/device checks remain mandatory; the change log records what could not be seen here.
