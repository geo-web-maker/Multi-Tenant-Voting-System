# SMS-TAB: Bulk SMS tab (docs: BULK_SMS_TAB_GUIDE.md)

## What changed
**Backend**
- `backend/sms_bulk.py` (new, pure): GSM-7/UCS-2 part counting, variable list + renderer (plain replace, no `str.format`), pricing validation, audience query builder (attribute keys accepted only if they are enabled org fields), first-valid-phone (splits `/`), exact estimate.
- `main.py`: `sms_pricing` and `sms_bulk_per_second` settings (defaults, `SmsBudgetUpdate`, validation, `log_action` + ledger via the existing budget handler, returned by `_sms_usage_payload`); `count_sms(..., n=1)`; endpoints `POST /admin/sms/audience`, `POST /admin/sms/send`, `GET /admin/sms/campaigns`, `GET /admin/sms/campaigns/{id}` (`?failed=1`), `POST .../cancel`, `POST .../retry-failed` (all superadmin); resumable background job; resume on boot.
- New tenant collections `sms_campaigns`, `sms_campaign_recipients` (registered in `tenant_db.py`, indexes in `main.py`, backup lists in `backup.py`; recipients expire after 90 days).
- Tests: `backend/tests/test_sms_bulk.py`.

**Frontend**
- `src/smsCalc.js` + `smsCalc.test.js` (same vectors as the backend tests).
- `components/SmsPanel.jsx` (Balances and usage, Compose, Calculator, Send, Settings) and `components/SmsSettings.jsx` (pricing, routing, test and check, budget; moved out of `SecurityPanel`).
- `SecurityPanel.jsx`: SMS routing, test, budget blocks and the usage tile removed; `SmsUsageTile` is still exported for other dashboards.
- `SuperAdminDashboard.jsx`: `sms` entry in `tabGroups` (Security group), `<SmsPanel />`, Voters > SMS sub-tab and unused balance code removed, "Security & SMS" renamed "Security". Copy in `ResetOtpLimitsPanel.jsx` updated.
- `uiTemplateRules.test.js`: `SmsPanel`, `SmsSettings` added to `KIT_PANELS`.

## Decisions (guide sections 2, 7.3, 14)
- Superadmin only. Pricing is per provider, saved through `_save_security`; unset cost is `None` and blocks the send (never shown as 0).
- The estimate uses the first provider of `sms_provider_order(sms_route_other, "notice")`; labelled an estimate.
- Conservation mode: bulk send is refused (409). Enforced budget: refused if parts exceed what remains.
- `count_sms` now counts parts for bulk sends (extra `parts - 1` counted after each successful or ambiguous send).
- One campaign at a time per organisation. A crash leaves a row in `sending`; on boot it becomes `ambiguous` and is never re-sent. "Retry failed" re-queues only definite failures.
- Recipients are pre-rendered at send time, one row per student (idempotent, no re-query).

## What was run
- `sms_bulk.py` tests: 27 cases pass using a small pytest stand-in (pytest is not installed here).
- `smsCalc.test.js`: 14 cases pass using a small vitest stand-in under node.
- `python -m py_compile` on `main.py`, `tenant_db.py`, `backup.py`, `sms_bulk.py`.
- JSX/JS syntax parse (TypeScript parser) of every changed frontend file.

## What was NOT run (no dependencies or network in the authoring environment)
- `pytest` for the whole backend suite (including `test_tenant_scoping_lint.py`, backup coverage tests) and the new endpoints/job against mongomock.
- `npx vitest run` in both templates, both `vite build`s, eslint.
- Any real SMS send, and any visual check (Default/Blueprint, light/dark, 1100 px / 390 px). The variable chips are `perf-btn` buttons inside `perf-chips` items: check they look right in both templates.
- Open: confirm each provider's real per-part billing and limits before trusting totals; consent/opt-out rules for bulk messages.

## Update: system-message calculator and balance boxes
**Backend**
- `backend/sms_templates.py` (new, pure): every automatic SMS in one catalog (OTP, staff login code, 9 applicant/Finance wordings, status link, 4 contact-change notices, connection test). `main.py` now renders them through `sms_templates.render(...)` at each send site, so the calculator prices exactly what is sent. Wording is unchanged (pinned by `tests/test_sms_templates.py`).
- `GET /admin/sms/templates` (superadmin): each message rendered with this organisation's name, longest real position title, highest fee and support contact, counted with the provider that kind really routes to (OTP follows the OTP route, everything else the other route) and priced from `sms_pricing`. Unset price is `null`, never 0.

**Frontend**
- `SmsPanel.jsx`: Balances and usage are now boxes (EgoSMS balance, MamboSMS balance, SMS budget left; red when 25% or less). The Calculator has a System messages section: enter how many of each you expect, see per-message and total cost, "Everything together" (with the campaign above), and each provider's balance after sending (red if negative). OTP has a "Use the voter count" shortcut.
- `smsCalc.js`: `systemTotals`, `toCount`, `balanceNumber`, `partsAffordable` (+ tests). A used message with no price makes the total "Not set", never a smaller number.
- `SecurityPanel.jsx`: `SmsUsageTile` takes `hideBudgetLeft` (the SMS tab shows the budget as a box instead).

**Finding:** with a long organisation name the OTP is 161 characters, which is 2 parts, so it bills double. Shorten the org name in the code or the wording if that matters.

**Run:** `test_sms_templates.py` (9 cases) and the new `smsCalc.test.js` cases pass under the same kind of stand-in as before; `py_compile` on `main.py`; TypeScript parse of the changed JSX.
**Not run:** pytest/vitest proper, eslint, vite build, the new endpoint against mongomock, any visual check (both templates, light/dark, 390 px).
