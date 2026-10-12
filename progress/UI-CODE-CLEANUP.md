# Code cleanup

- **Date:** 12 October 2026
- **Status:** Source changes applied; automated/browser verification incomplete where noted.

## Changed

Deleted unimported AdminDashboard.jsx after source import scan. Removed redundant `PerformanceSettings.jsx` inline field styles. Moved pure helpers from BackupUI.jsx into BackupUtils.js and updated imports to avoid component-file non-component exports.

## Verification

No npm lint/tests/build because dependencies are missing. No import/parser build could be run.
