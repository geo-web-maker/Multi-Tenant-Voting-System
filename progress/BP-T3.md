# BP-T3 — Voter flow
status: done
branch: improvements/BP-T3 (no git repo in the supplied zip; changes are in the working tree)
commits: n/a
tests added: components/PhaseBanner.template.test.jsx (8), components/OtpInput.template.test.jsx (6), Login.template.test.jsx (3) = 17 new; 418 total
results (default):   frontend 418 passed, 0 failed · lint 0/0 · build ok
results (blueprint): frontend 418 passed, 0 failed · build ok (existing PhaseBanner/LoginErrorActions/OtpInput/App.* tests pass unchanged)
baseline at branch cut: frontend 401 · entry gz 34,804 B (BP-T2)
gates: G1/G2 pass (see numbers in the build output below if re-run) · G3 pass (418 = 418) · G4 data-track labels OK · G5 lint 0/0
files:
- default files, seams only: PhaseBanner.jsx (branch after all hooks -> bp.PhaseBannerView), OtpInput.jsx (branch after hooks -> bp.OtpScreen; all state/handlers stay), VoterLoginInputs.jsx (-> bp.VoterFields with real labels), LoginErrorActions.jsx (class hook only), App.jsx (step 1/1.5/2: `cardProps()`, `k?.…` class hooks, labels for admin email/password/authenticator, only when bp).
- templates/blueprint/: PhaseBannerView.jsx, OtpScreen.jsx, OtpCells.jsx, VoterFields.jsx, labels.js (`cls`, PHASE_VARIANT), primitives.jsx (FieldLabel), index.js, blueprint.css (login/otp controls, banner parts, otp overlay/err/lock).
decisions applied: E2 (4 banner variants), E6 (one input, six presentation cells), D2/D3 (control borders line-ui; banner text uses --bp-tx, never accent on tint).
deviations from the card:
- `bp-` literals cannot live in default JS (gate G1), so default files call `bp.<Component>` or read `bp.cls.*`; no hex or class string is added to them.
- PhaseBanner/OtpInput use a late branch after all hooks (R12 satisfied without renaming to DefaultX).
- The OTP input is the only input; it is overlaid at opacity 0 over the cells and named by the heading via aria-labelledby (no new copy).
- Placeholder-only fields get labels only in blueprint: voter reg no. / full name, admin email / password / authenticator code. Label text reuses the placeholder wording without the "e.g." part.
- Login-error modal, resend row, "Return Home" and the Turnstile area are NOT restyled here: the modal inherits via N4 + bridge; step 4 belongs with the ballot done view (T4). Check them in the HUMAN pass.
- `needsTotp` field gets `id="admin-totp"` only in blueprint.
HUMAN checks pending (jsdom cannot cover): real phone SMS autofill fills the code; paste works; keyboard does not hide Verify at 360x640; screen reader announces ONE field; error/lock look in light and dark; login-error modal buttons legible; Turnstile widget placement inside the new card.
next step: BP-T4 (ballot), T5 (results), T6 (apply) can run in parallel; T3 done.
