# Any admin can join the panel with no separate login
- `POST /superadmin/vetting-panel/link-commissioner` {student_id, appointment_reason} (route name kept). Accepts anyone
  holding ANY admin role: commissioner, IT admin, overseer, financial controller. Reason is required and goes to the audit
  trail (`vetting_panel_member_added`, `linked_commissioner: true`, `linked_roles: [...]`).
- Creates an ACTIVE member record linked by student_id with no email, no password, no SMS. The person opens the panel
  with `/admin/switch-hat` from a "Switch to Vetting Panel" button on their own dashboard (`PanelHatButton`; the
  commissioner screen keeps its own copy because it also shows the chair's tie hint).
- The panel token carries `via_hat` and `hat_role` (the role it came from). Switching back returns to that role and
  re-checks they still hold it. Response includes `back_to` / `back_label` for the button text.
- Same guards as a normal appointment: panel frozen while vetting is open, no live application, no duplicates.
- Picker: `GET /superadmin/panel-eligible-admins` lists every admin-role holder with role labels (Vetting Panel tab > Add to the Panel > Admins).
- `GET /admin/panel-link` now answers for all four admin roles and returns `overseer_paused`.

## Rulings
- **Overseer:** allowed, but overseer access is PAUSED while they serve (enforced in `auth_guard_middleware`: every
  overseer request except switch-hat, panel-link, set-password and logout gets 403 `code: overseer_paused`). They can reach the
  panel but cannot switch back while their record is active; when service ends (deactivated, access ended) a normal overseer
  login works again. Superadmin "view as" sessions are exempt. The overseer dashboard shows an "Overseer access paused" notice.
- **Financial controller:** allowed with NO rule. A person can clear a payment and judge the same candidate. This is
  deliberate: discouraged by people, not blocked by the system. If that changes, add the check in the vote route.
- A person holding several roles returns to the role they switched from.
