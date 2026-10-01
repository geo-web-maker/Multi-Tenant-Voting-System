// Casting a ballot over a weak connection (guide 4.8 #2-#4).
//
// The server makes a repeat submit harmless (one ballot, "already cast your vote" the second time), but the
// voter used to be told "Connection failed" when only the RESPONSE was lost, tapped again, and then saw
// "already voted" as an error — unable to tell whether the vote counted. These helpers turn every outcome
// into one of a few explicit kinds so the UI can say the true thing.

/** @returns {{kind: 'success'|'already_recorded'|'session_expired'|'error'|'no_response', message?: string, detail?: string}} */
export async function castBallot(api, studentId, candidateIds) {
  try {
    const res = await api.post('/vote-bulk', { student_id: studentId, candidate_ids: candidateIds });
    if (res.data?.status === 'success') return { kind: 'success' };
    return { kind: 'error', message: 'Unexpected response from the server. Please try again.' };
  } catch (err) {
    const status = err.response?.status;
    const detail = err.response?.data?.detail;
    if (status === 401) return { kind: 'session_expired', detail };
    // The voter reached the ballot only because they had NOT voted at login, so "already cast" now means
    // a ballot of theirs was recorded (typically: our first request succeeded and its reply was lost).
    if (status === 400 && /already cast your vote/i.test(String(detail || ''))) return { kind: 'already_recorded' };
    if (err.response) return { kind: 'error', message: typeof detail === 'string' ? detail : 'Submission failed. Please try again.' };
    return { kind: 'no_response' };   // timeout / offline / dropped connection: outcome unknown
  }
}

/** true = vote is recorded, false = it is not, null = could not find out. */
export async function checkVoteStatus(api, studentId) {
  try {
    const res = await api.get('/vote-status', { params: { student_id: studentId } });
    return Boolean(res.data?.has_voted);
  } catch {
    return null;
  }
}
