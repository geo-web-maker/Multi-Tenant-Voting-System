# Approval policy: what it means today

## The short version

`approval_policy` is a real per-org setting now (`db.settings`, `security_settings`),
editable from the Security tab. It governs **two separate votes**:

- **Application approval/denial** — cast by the **Vetting Panel** (`vetting` role,
  `POST /admin/applications/{id}/vote`). Commissioners vote here only if they also
  sit on the panel, and only through the panel hat (`/admin/switch-hat`).
- **Candidate removal** — still cast by **commissioners** directly
  (`POST /admin/applications/{id}/vote-remove`); this stayed out of the panel split
  (guide decision 3) and uses the same `approval_policy` value.

```python
# backend/main.py — same formula, read from the org's approval_policy
required = (total // 2) + 1          # majority_total
```

## The three policies

| Policy | Resolves when |
|---|---|
| `unanimous` | every panelist (or, for removals, every commissioner) agrees |
| `majority_total` | either side reaches `floor(total/2)+1` of the full panel/commissioner count, even before everyone's voted |
| `majority_cast` | after everyone active has weighed in, whichever side has more wins |

`CommissionDashboard.jsx` and `ApplicantPortal.jsx` now read the live policy and
show the matching copy — there's no more hardcoded "Full consensus" string to go
stale when the count changes.

## Seed data to test this by hand

Run `python seed_test_data.py` then `python seed_advanced_scenarios.py`. Every
seeded commissioner / IT admin / financial controller account uses the password
`SeedTest123!` — the script prints each email as it runs. The P1 migration carries
every seeded commissioner into `panel_members`, so to cast an application vote,
log in as the commissioner and switch to the Vetting Panel hat in the UI (or via
`POST /admin/switch-hat`) before voting; removal votes use the commissioner login
directly.

### Org `nomtest` — 5 panelists (migrated from 5 commissioners)

- **President — Candidate A**: 2 of 5 panelists approved (`commissioner0`,
  `commissioner1`). One vote short of the 3-vote majority. Log in as
  `commissioner2@nomtest.local`, `commissioner3@nomtest.local`, or
  `commissioner4@nomtest.local`, switch to the panel hat, and cast the deciding
  vote — try approve *and* deny on separate re-runs to see both outcomes.
- **President — Candidate B**: 1 approve / 1 deny already cast, contested.
  Two more votes either way resolves it.
- **Secretary General**: finance-cleared, **zero** votes cast — the full
  flow from a clean slate.
- **Treasurer**: already resolved (3/5 approved) by the script, so there's
  a real approved candidate — and a removal vote already in progress
  against them (1 of 5 commissioners voted to remove, via the commissioner
  login, not the panel hat). Finish that removal vote as a different
  commissioner to see a candidate actually get removed.
- **Contact changes**: one pending, one approved, one denied, one
  cancelled — `GET /admin/contact-changes` (or the Contact Changes tab) to
  see all four statuses at once.
- **Exception grants**: one active/no-expiry, one active/expires in 2
  hours, one already expired by the time the script finishes — so the
  Exception Grants list shows all three states without waiting.

### Org `racetest` — Live Results / mobile layout stress testing

Five positions, each engineered for a different shape:

| Position | Candidates | Vote split (of 100 cast) |
|---|---|---|
| Tight Race — President | 2 | 52 / 48 |
| Landslide — Vice President | 2 | 90 / 10 |
| Unopposed — General Secretary | 1 | 100 / — |
| Three-Way — Treasurer | 3 | 50 / 30 / 20 |
| Long Names — Publicity Secretary | 2 (deliberately long names) | 55 / 45 |

100 of the 120 imported voters cast real ballots through
`/verify-identity` → `/verify-otp` → `/vote-bulk` (not DB inserts, so
`vote_events` and `has_voted` are both real). The remaining **20 voters are
untouched** — use them for your own manual voting-flow or search testing.

Worth checking while you're in here: the lead/percentage badge on
Commission/Overseer dashboards only ever compares `candidates[0]` vs
`candidates[1]` — confirm that's intentional for the Three-Way Treasurer
race, since a 3-way split is exactly the case that would expose it if not.

### Both orgs

Each has its own branding (name/colors/logo placeholder) via
`POST /superadmin/branding`, so the boot splash and official report
signature block render distinctly per org.

`nomtest`'s voter roster also has the phone-number edge cases from our
earlier conversation baked in (zero numbers, a duplicate that should
dedupe, two distinct numbers, and one malformed number that should warn
without rejecting the row) — `nom-voter-05` through `nom-voter-08`.
