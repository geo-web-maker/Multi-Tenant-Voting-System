import { describe, it, expect } from 'vitest';
import { castBallot, checkVoteStatus } from './voteOutcome';

const fail = (response) => Object.assign(new Error('x'), response === undefined ? {} : { response });
const apiWith = ({ post, get }) => ({ post: async () => { if (post instanceof Error) throw post; return post; }, get: async () => { if (get instanceof Error) throw get; return get; } });

describe('castBallot', () => {
  it('success', async () => {
    expect(await castBallot(apiWith({ post: { data: { status: 'success' } } }), 'v1', ['a'])).toEqual({ kind: 'success' });
  });
  it('treats "already cast your vote" as a recorded ballot, not an error', async () => {
    const e = fail({ status: 400, data: { detail: 'You have already cast your vote.' } });
    expect((await castBallot(apiWith({ post: e }), 'v1', ['a'])).kind).toBe('already_recorded');
  });
  it('401 means the session expired', async () => {
    const e = fail({ status: 401, data: { detail: 'expired' } });
    expect(await castBallot(apiWith({ post: e }), 'v1', ['a'])).toEqual({ kind: 'session_expired', detail: 'expired' });
  });
  it('other server answers are shown as errors with the server message', async () => {
    const e = fail({ status: 400, data: { detail: 'Only one candidate can be selected per position.' } });
    expect(await castBallot(apiWith({ post: e }), 'v1', ['a'])).toEqual({ kind: 'error', message: 'Only one candidate can be selected per position.' });
  });
  it('a missing response (timeout/offline) is "unknown outcome", never a plain failure', async () => {
    expect((await castBallot(apiWith({ post: new Error('Network Error') }), 'v1', ['a'])).kind).toBe('no_response');
  });
});

describe('checkVoteStatus', () => {
  it('maps true / false / unknown', async () => {
    expect(await checkVoteStatus(apiWith({ get: { data: { has_voted: true } } }), 'v1')).toBe(true);
    expect(await checkVoteStatus(apiWith({ get: { data: { has_voted: false } } }), 'v1')).toBe(false);
    expect(await checkVoteStatus(apiWith({ get: new Error('net') }), 'v1')).toBeNull();
  });
});
