import { describe, it, expect } from 'vitest';
import { filenameFromDisposition, exportErrorMessage } from './registerExport';

describe('filenameFromDisposition', () => {
  it('reads a quoted filename', () =>
    expect(filenameFromDisposition('attachment; filename="voter-register-assk-full-20260930-1200.xlsx"', 'x')).toBe('voter-register-assk-full-20260930-1200.xlsx'));
  it('falls back when header is missing/hidden by CORS', () => expect(filenameFromDisposition(undefined, 'voter-register.csv')).toBe('voter-register.csv'));
  it('strips path separators', () => expect(filenameFromDisposition('attachment; filename="../../x.csv"', 'f')).not.toMatch(/[\\/]/));
});

describe('exportErrorMessage', () => {
  it('parses a JSON Blob body', async () => {
    const blob = new Blob([JSON.stringify({ detail: 'Voter register export is not enabled for your account.' })]);
    expect(await exportErrorMessage({ response: { status: 403, data: blob } })).toMatch(/not enabled/);
  });
  it('handles the view-only pre-flight rejection (plain object)', async () =>
    expect(await exportErrorMessage({ response: { status: 403, data: { detail: 'Read-only view: this action is disabled.' } } })).toMatch(/Read-only/));
  it('handles no response (network/timeout)', async () =>
    expect(await exportErrorMessage({})).toMatch(/No response/));
  it('falls back on an unparseable blob', async () =>
    expect(await exportErrorMessage({ response: { status: 500, data: new Blob(['<html>']) } }, 'fallback')).toBe('fallback'));
});
