# UI pending work — implementation status, 12 October 2026

This file closes the repository copy of the work list supplied for this pass. The original requirements are retained below as a status-oriented checklist. Details: `UI_AUDIT_2026-10-12.md`, `UI_TEMPLATE_MANUAL.md`, `DEVIATIONS.md`, and the per-card notes under `progress/`.

## Completed in the working tree

- [x] Baseline inspection: shared panel kit and one Blueprint stylesheet were already present. `ui-pattern-reconciliation.patch` was not in the supplied archive, so no unavailable patch was applied.
- [x] Recorded decisions: navy primary buttons, red destructive buttons, accept the shared kit's intentional default-template appearance changes, remove `AdminDashboard.jsx` after import check.
- [x] Migrated 162 button/style usages across priority admin dashboard and small-panel files to `perf-btn` classes; selected filter/mode controls use `aria-pressed`. Retained explained exceptions in `LEGACY_BUTTON_FILES`.
- [x] Token fallbacks for App shell / ClosedNotice / ViewAsBanner / BallotBox / icon status colours. Deliberate public status, brand and print exceptions are documented.
- [x] Deleted unimported `AdminDashboard.jsx`.
- [x] Removed redundant `PerformanceSettings.jsx` inline field style.
- [x] Moved pure backup helpers from `BackupUI.jsx` to `BackupUtils.js`, updating imports.
- [x] Reduced screen JSX hex count and lowered `HEX_CEILING` from 389 to 294.
- [x] Static UI-template checks mirrored in Python: pass; no stale allow-list entries; all statically referenced `perf-*` classes have CSS definitions; one Blueprint stylesheet.
- [x] Created progress notes and updated deviations/audit/manual.

## Checks blocked or requiring a real browser / environment

- [ ] `npm run test -- --run` (default): not run; frontend dependencies are unavailable in this sandbox.
- [ ] `VITE_UI_TEMPLATE=blueprint npm run test -- --run`: not run; frontend dependencies unavailable.
- [ ] `npm run lint`: not run; npm dependency install did not complete. The `BackupUI` export issue was addressed by moving pure helpers, but lint is not claimed as passing.
- [ ] Default and Blueprint Vite builds: not run for the same dependency blocker.
- [ ] Backend pytest: attempted; collection fails immediately because `mongomock` is missing. Install `backend/requirements-dev.txt` in CI/local environment and rerun.
- [ ] Browser visual pass: still required for both templates, light/dark, desktop (~1100 px) and phone (390 px), especially all tabs of migrated dashboards and Backups / Nomination Form / Demo Controls / Performance. Test real data, long names, errors, many rows, no horizontal overflow and 44/48 px targets.
- [ ] Real-device checks and accessibility walk (keyboard/screen reader, 200% zoom) remain human checks.
- [ ] BK-12 restore test still retains merged restore documents for all tenants in memory. The existing note says this is acceptable at current size; revisit when data growth justifies the redesign. `restore_tenant` guard tests protect future changes but do not prove the earlier refactor preserved behaviour.
- [ ] Commit: impossible in this archive because it contains no `.git` metadata. A forward patch is supplied separately with this handoff.
- [x] Delivery safety: the completed ZIP and forward patch exclude `backend.env`, `frontend.env`, and `backend/loadtest.env`; only `.env.example` templates are retained. Rotate credentials if the original archive was shared or committed, as the project runbook warns.

## Remaining exceptions

`LEGACY_BUTTON_FILES` has 20 entries with reasons in `progress/UI-BUTTONS-REMAINDER.md`. `CandidateStatusPortal.jsx` maintains its separate public palette under guide D9; `PhaseBanner.jsx` uses its theme map; WhatsApp green in HelpPanel and print-document hex colours remain deliberate. This is a documented exception, not an assertion that these pages were visually verified.
