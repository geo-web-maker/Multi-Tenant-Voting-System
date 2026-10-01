// D2d: map the backend `alerts` list ([{kind, level, metric, value, threshold}]) to display state. Pure.
export const ALERT_LABELS = { healthy: 'Healthy', warning: 'Warning', critical: 'Critical' };
const RANK = { healthy: 0, warning: 1, critical: 2 };

export const alertLevel = (level) => (level === 'critical' ? 'critical' : 'warning'); // unknown levels are never shown as healthy

export function overallAlertState(alerts) {
  if (!Array.isArray(alerts) || alerts.length === 0) return 'healthy';
  return alerts.reduce((worst, a) => (RANK[alertLevel(a?.level)] > RANK[worst] ? alertLevel(a.level) : worst), 'healthy');
}

export const alertLabel = (state) => ALERT_LABELS[state] || ALERT_LABELS.warning;
