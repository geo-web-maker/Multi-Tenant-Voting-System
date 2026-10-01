"""
App-wide critical-failure alerting (Task: extend backup's email alert to every
critical system).

This is the same Resend-based sender that used to live only in backup.py,
pulled out so any module can raise an alert the same way. Behavior preserved:
- Never raises. A failed alert is logged loudly instead of crashing the caller.
- Uses Resend's HTTPS API (Render's free tier blocks outbound SMTP ports).

Added on top of the original:
- `level`: "critical" | "warning" | "info" — tags the subject line so your
  inbox/filters can separate must-see-now from can-wait-till-morning.
- Per-subject cooldown so one bad deploy or a flapping dependency can't spam
  Resend / your inbox with hundreds of identical emails in a few minutes.
  This is in-process memory (resets on redeploy) — good enough for a single
  always-on backend instance; move to a `alert_cooldowns` collection if you
  ever run more than one instance of this service.
"""
import logging
import os
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger("BallotBoxAlerts")

# subject -> last-sent time, per process
_last_sent: dict[str, datetime] = {}

# Default cooldown per level. "critical" still throttles (a crash-looping
# endpoint firing 50x/minute is not more actionable than firing once) but
# recovers faster than warning/info so a second, genuinely new incident of
# the same shape within a few minutes still gets through.
_DEFAULT_COOLDOWN_S = {
    "critical": 5 * 60,
    "warning": 30 * 60,
    "info": 60 * 60,
}


def _now() -> datetime:
    return datetime.utcnow()


async def send_alert(subject: str, body: str, level: str = "critical",
                      cooldown_s: int | None = None) -> bool:
    """Email the superadmin via Resend's HTTPS API. Never raises.

    `level` is prefixed onto the subject ("[BallotBox:CRITICAL] ...") and
    picks the default cooldown; pass `cooldown_s` to override it for a
    specific call site (e.g. 0 to force-send regardless of recent duplicates).
    """
    cooldown = _DEFAULT_COOLDOWN_S.get(level, 15 * 60) if cooldown_s is None else cooldown_s
    key = f"{level}:{subject}"
    last = _last_sent.get(key)
    if cooldown > 0 and last is not None and (_now() - last).total_seconds() < cooldown:
        logger.info("Alert suppressed (cooldown %ss, %.0fs ago): %s",
                    cooldown, (_now() - last).total_seconds(), subject)
        return False
    _last_sent[key] = _now()

    api_key = os.getenv("RESEND_API_KEY")
    to = os.getenv("BACKUP_ALERT_EMAIL") or os.getenv("SUPER_ADMIN_ID", "")
    sender = os.getenv("ALERT_FROM_EMAIL", "BallotBox Alerts <onboarding@resend.dev>")
    tagged_subject = f"[BallotBox:{level.upper()}] {subject}"
    if not api_key or "@" not in to:
        logger.error("ALERT NOT EMAILED (RESEND_API_KEY or recipient missing): %s | %s",
                     tagged_subject, body)
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"from": sender, "to": [to], "subject": tagged_subject, "text": body},
            )
        if r.status_code >= 300:
            logger.error("Alert email rejected (%s): %s", r.status_code, r.text[:300])
            return False
        return True
    except httpx.HTTPError as e:
        logger.error("Alert email failed: %s | original alert: %s", e, tagged_subject)
        return False


async def alert_critical(subject: str, body: str, cooldown_s: int | None = None) -> bool:
    """Tier 1 — fire immediately. Vote-write failures, DB loss, backup
    failures, auth outages, any unhandled 5xx on a write endpoint."""
    return await send_alert(subject, body, level="critical", cooldown_s=cooldown_s)


async def alert_warning(subject: str, body: str, cooldown_s: int | None = None) -> bool:
    """Tier 2 — degraded but not down. Elevated error rates, slow queries,
    non-backup cron failures, cert-expiry warnings. Longer cooldown so these
    read as a digest rather than a stream."""
    return await send_alert(subject, body, level="warning", cooldown_s=cooldown_s)


def alert_on_failure(subject: str, level: str = "critical"):
    """Decorator for scheduled jobs / background tasks: on an unhandled
    exception, email the alert (with the exception attached) and re-raise so
    the job's own error handling/logging still runs unchanged.

    Usage:
        @alert_on_failure("Nightly report generation failed", level="warning")
        async def generate_nightly_report(): ...
    """
    def deco(fn):
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                await send_alert(subject, f"{type(e).__name__}: {e}", level=level)
                raise
        return wrapper
    return deco
