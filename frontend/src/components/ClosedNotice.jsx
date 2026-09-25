/* eslint-disable react-refresh/only-export-components */
import React from 'react';
import { fmtZoned } from '../tz';

// One notice for "this can't be done right now", used everywhere the same
// situation occurs. Previously the master switch showed a yellow banner while
// a scheduled close only surfaced as an error dialog after clicking.
// It is informational only: buttons keep working, the server stays the
// authority (exception grants can still let a specific student through).

const noticeStyle = {
  backgroundColor: '#fff3cd', color: '#856404', padding: '10px', borderRadius: '6px',
  marginBottom: '15px', textAlign: 'center', fontSize: '14px', border: '1px solid #ffeeba',
};

/** Text for the voting notice, or null when voting is open. */
export function votingNoticeText(status) {
  if (!status) return null;
  if (status.is_open === false) return 'The election is currently closed.';
  if (status.voting_phase === 'not_started') {
    return status.voting_opens_at
      ? `Voting has not started yet. It opens ${fmtZoned(status.voting_opens_at, status.timezone)}.`
      : 'Voting has not started yet.';
  }
  if (status.voting_phase === 'ended') {
    return status.voting_closes_at
      ? `The voting period has ended. It closed ${fmtZoned(status.voting_closes_at, status.timezone)}.`
      : 'The voting period has ended.';
  }
  // Closed by the schedule but we don't know which side of the window we're on.
  if (status.voting_phase_open === false) return 'Voting is not currently open.';
  return null;
}

/** Text for the commissioner vetting notice, or null when the vetting window is open. */
export function vettingNoticeText(status) {
  if (!status) return null;
  if (status.vetting_phase === 'not_started') {
    return status.vetting_opens_at
      ? `Vetting has not started yet. Commissioners can vote from ${fmtZoned(status.vetting_opens_at, status.timezone)}.`
      : 'Vetting has not started yet.';
  }
  if (status.vetting_phase === 'ended') {
    return status.vetting_closes_at
      ? `The vetting period has ended. It closed ${fmtZoned(status.vetting_closes_at, status.timezone)}.`
      : 'The vetting period has ended.';
  }
  if (status.vetting_phase_open === false) return 'Vetting is not currently open.';
  return null;
}

/** Text for the applications notice, or null when applications are open. */
export function applicationsNoticeText(status) {
  if (!status) return null;
  if (status.applications_phase === 'not_started') {
    return status.applications_opens_at
      ? `Applications have not opened yet. They open ${fmtZoned(status.applications_opens_at, status.timezone)}.`
      : 'Applications have not opened yet.';
  }
  if (status.applications_phase === 'ended') {
    return status.applications_closes_at
      ? `The applications period has ended. It closed ${fmtZoned(status.applications_closes_at, status.timezone)}.`
      : 'The applications period has ended.';
  }
  if (status.applications_phase_open === false) return 'Applications are not currently open.';
  return null;
}

export default function ClosedNotice({ text, style }) {
  if (!text) return null;
  return (
    <div style={{ ...noticeStyle, ...style }} role="status">
      <strong>Notice:</strong> {text}
    </div>
  );
}
