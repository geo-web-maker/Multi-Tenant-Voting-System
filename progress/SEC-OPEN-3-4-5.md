# SEC "Open" items 3, 4, 5

## 3. Ballot-secrecy timing (done)
- `vote_events.cast_at` is rounded DOWN to a bucket (`VOTE_TIME_BUCKET_SECONDS`, default 600).
- `vote_events._id` is now bucket-ordered but random inside a bucket (timestamp = bucket end + 8 random bytes), so
  insertion order can no longer be matched to the order of `vote_cast` rows in `audit_log`.
- `vote_cast` audit rows are stamped with the same bucket start (`log_action(..., timestamp=)`).
- `create_audit_checkpoint` only folds in buckets that ended more than 60 s ago, so no event can land behind a
  checkpoint's `to_id`. Consequence: the newest ballots join the chain up to ~11 minutes after they are cast
  (bucket + grace). Run the final checkpoint at least that long after voting closes.
- Old events keep their precise values and still verify (the chain hashes whatever is stored). Not retro-fitted:
  a database that already holds real ballots still has the old precision for those rows.
- Deploy outside live voting if you can: new ids are always larger than old ones, so a mid-election deploy is safe,
  but the secrecy gain only applies to ballots cast after it.

## 4. Login throttling (partly done)
- Added a per-email counter shared by all IPs (`LOGIN_EMAIL_MAX_ATTEMPTS`, default 20, 15 min lock; the superadmin
  email keeps the short capped lock). A successful login clears both counters.
- NOT done: superadmin 428-after-correct-password and TOTP replay. Both change the login flow
  (frontend + API) and need your decision.

## 5. Data minimisation (done)
- `/admin/applications` no longer returns `payment_method`, `payment_proof_url`, `finance_clear_note` or
  `finance_rejection_reason` to anyone except the Financial Controller and the superadmin. `finance_cleared`,
  `finance_rejected` and `fee_required` still go to every role (the vetting and overseer screens use them).

Tests: `backend/tests/test_ballot_secrecy_throttle_minimisation.py` (15).
