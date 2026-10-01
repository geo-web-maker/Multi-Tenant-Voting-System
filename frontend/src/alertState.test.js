import { describe, it, expect } from 'vitest';
import { overallAlertState, alertLabel, alertLevel } from './alertState';

describe('D2d: alert state mapping', () => {
  it('empty or missing list is Healthy', () => {
    expect(alertLabel(overallAlertState([]))).toBe('Healthy');
    expect(alertLabel(overallAlertState(undefined))).toBe('Healthy');
  });
  it('warning-only is Warning, any critical wins', () => {
    expect(alertLabel(overallAlertState([{ kind: '429', level: 'warning' }]))).toBe('Warning');
    expect(alertLabel(overallAlertState([{ kind: '429', level: 'warning' }, { kind: '5xx', level: 'critical' }]))).toBe('Critical');
  });
  it('an unknown level is never shown as healthy', () => {
    expect(alertLevel('weird')).toBe('warning');
    expect(overallAlertState([{ kind: 'x', level: 'weird' }])).toBe('warning');
  });
});
