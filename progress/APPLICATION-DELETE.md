# Card: superadmin delete of an application (soft or hard)

## What changed
- **Backend (`main.py`)**: `POST /superadmin/applications/{id}/delete` (`mode` soft|hard, mandatory reason, hard also needs `confirm: "DELETE"`);
  `GET /superadmin/deleted-applications`; `POST /superadmin/deleted-applications/{id}/restore` and `/purge`.
  Soft delete MOVES the document to a new tenant collection `deleted_applications`, so every existing query on `applications`
  (lists, vetting, finance, counts) excludes it with no filter changes. Restore returns it as `pending`.
- Both modes: refused (409) once votes were cast for the candidate; take an approved candidate off the ballot; revoke the certificate;
  revoke the student's status links only when they have no other application. Hard delete also removes the signed nomination form
  (record + stored file). Cloudinary photo/receipt files are NOT deleted. Audit actions: `application_soft_deleted`,
  `application_hard_deleted`, `application_restored`, `application_purged`.
- `deleted_applications` registered in `tenant_db.TENANT_COLLECTIONS`, `backup.FULL_COLLECTIONS` + `ASSET_FIELDS`,
  `wipe_election_data.ALWAYS_WIPE`, `LEGACY_TENANT_COLLECTIONS`, `DEMO_TAGGED_COLLECTIONS`.
- **Frontend**: "Delete application" (`perf-btn perf-btn-danger`) on each card in the superadmin Applications tab; new kit-only
  `DeletedApplicationsPanel.jsx` (archive with Restore / Delete permanently) under the list.

## Deliberate departure (see manual sections 2 and 5)
- `UIFeedback.prompt` gained `options` (radio choice, resolves `{option, text}`) and `minLength`. The soft/hard picker therefore uses the
  existing template-aware dialog instead of a new hand-styled modal. Behaviour without these options is unchanged.
- Blueprint NEUTRALISER N14 selector is now `.ui-dialog input:not([type="radio"])` so the radios keep their native control.

## Not run (no dependencies in the authoring sandbox)
- `pytest backend/tests/test_application_delete.py` (and the whole backend suite incl. tenant-scoping lint and backup coverage tests).
- `npx vitest run` in default and Blueprint templates; lint; both Vite builds.
- Browser pass in both templates, light/dark, 1100 px and 390 px: the delete dialog (both options, Blueprint pill buttons, radios) and the archive panel.
