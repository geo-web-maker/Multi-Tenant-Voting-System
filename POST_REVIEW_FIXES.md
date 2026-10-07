# Post-review fixes (nomination form + demo mode)

1. **Submitted forms unreadable after 24h (serious).** `nomination_uploads` had a TTL index on `created_at`, which also
   deleted *attached* records the application depends on. The TTL is gone (startup drops the legacy `created_at_1`
   index). `_sweep_stale_nomination_uploads()` now removes only stale *pending* uploads, deleting the private file and
   then the record; it runs opportunistically after each upload. Claim rollback restores `created_at`.
2. **Orphaned private files.** Sweep and demo reset now call `nomination_storage.delete_object`.
3. **Demo inbox needed a reload.** `DemoInbox.jsx` keeps checking every 30s while off (5s while on).
4. **Inbox rate limit** raised 30 -> 120 requests/min/IP (shared campus NAT).
5. **Demo reset reason** is now required (`DemoReasonRequest`).

Tests added: `tests/test_nomination_retention.py` (5), `test_reset_requires_a_reason` in `test_demo_mode.py`.
Not run here (no dependencies/network): pytest, vitest, eslint, vite. Run them before deploying.
