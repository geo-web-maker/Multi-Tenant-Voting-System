# Commissioner voting: what "consensus" actually means today

## The short version

There is **no policy toggle** in the code right now. Both application approval
and candidate removal use one hardcoded rule, in `backend/main.py`:

```python
required = (total // 2) + 1  # majority of TOTAL commissioner count
```

(`_resolve_application`, line ~1155, and `_resolve_removal`, line ~1208 — same
formula in both.)

This resolves the moment either side reaches `floor(total/2)+1`, counting
**every commissioner**, not just the ones who've voted. It is **not** full
consensus/unanimity, even though the frontend copy currently says "Full
consensus required for approval or removal."

That copy isn't lying by accident — it's only true because of arithmetic:
with exactly **2** commissioners, `floor(2/2)+1 = 2`, i.e. majority-of-total
happens to equal unanimity. The moment you add a 3rd commissioner, 2 of 3
resolves it without the third person ever voting, and the "Full consensus"
label becomes wrong.

## The three policies worth naming

| Policy | Resolves when | Currently implemented? |
|---|---|---|
| **Unanimous** | every commissioner agrees | No |
| **Majority of total** (current) | either side hits `floor(total/2)+1`, even before everyone's voted | Yes — the only behavior that exists |
| **Majority of votes cast** | after voting closes / everyone's weighed in, whichever side has more wins | No |

## How to get the behavior you want *today*, without a code change

Since the formula is fixed, the only lever you have is **how many people are
commissioners**:

- **Want effective unanimity?** Keep the commissioner count small and odd
  isn't even required — with `N` commissioners, majority-of-total only equals
  unanimity when `N` is 1 or 2. At `N=3`, 2 people can already decide it
  without the third. There's no commissioner count above 2 that gives you
  real unanimity under this formula — plan around that, don't rely on it.
- **Want a real majority-of-total with room for disagreement?** Any `N ≥ 3`
  already does this — that's the current behavior, no setup needed.
- **Want majority-of-votes-cast instead** (decide only once voting is
  closed, based on who actually showed up)? Not available without a code
  change — see below.

## If you want the actual toggle built

This needs a real (small) backend change: an `approval_policy` field on the
org's settings doc (`db.settings`, `{name: "security_settings"}` is the
natural home, next to the other per-org knobs already there), read by both
`_resolve_application` / `_resolve_removal`, plus fixing the two hardcoded
"Full consensus" strings in `CommissionDashboard.jsx` /
`OverseerDashboard.jsx` to reflect whichever policy is actually active. I
didn't build this — say the word and I will, with the default kept at
majority-of-total so existing orgs see zero behavior change.

## What the seed script (`seed_advanced_scenarios.py`) set up for you to test this by hand

Run it after the backend is up (`python seed_test_data.py` first if you
haven't, then `python seed_advanced_scenarios.py`). Every seeded
commissioner / IT admin / financial controller account uses the password
`SeedTest123!` — the script prints each email as it runs.

### Org `nomtest` — 5 commissioners, so majority (3) and unanimity (5) actually diverge

- **President — Candidate A**: 2 of 5 commissioners approved (`commissioner0`,
  `commissioner1`). One vote short of the 3-vote majority. Log in as
  `commissioner2@nomtest.local`, `commissioner3@nomtest.local`, or
  `commissioner4@nomtest.local` and cast the deciding vote — try approve
  *and* deny on separate re-runs to see both outcomes.
- **President — Candidate B**: 1 approve / 1 deny already cast, contested.
  Two more votes either way resolves it.
- **Secretary General**: finance-cleared, **zero** votes cast — the full
  flow from a clean slate.
- **Treasurer**: already resolved (3/5 approved) by the script, so there's
  a real approved candidate — and a removal vote already in progress
  against them (1 of 5 votes to remove). Finish that removal vote as a
  different commissioner to see a candidate actually get removed.
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
