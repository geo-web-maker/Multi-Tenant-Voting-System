# Commissioners join the panel with no separate login
- `POST /superadmin/vetting-panel/link-commissioner` {student_id, appointment_reason}. Reason is required and is
  written to the audit trail (`vetting_panel_member_added`, `linked_commissioner: true`).
- Creates an ACTIVE member record linked by student_id with no email, no password, no SMS. The commissioner opens the
  panel with the existing hat switch (`/admin/switch-hat`) from their Commission screen.
- Same guards as a normal appointment: panel frozen while vetting is open, no live application, no duplicates.
- UI: Vetting Panel tab > Add to the Panel > Commissioners (reason only). Voter roll / Outside person still use credentials.
