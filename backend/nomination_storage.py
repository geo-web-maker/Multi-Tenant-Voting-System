"""Private storage for completed (signed) nomination forms: Backblaze B2 through its S3 API (phase N2).

These files carry signatures and ID details, so they live in a PRIVATE bucket and are never given a
permanent URL. The browser only ever receives a presigned link that expires in a few minutes.

Credentials are deliberately separate from the backup / audit-anchor B2_* values: a bug in the upload route
must not be able to reach the backups. Use a dedicated bucket (or at least an application key restricted
to this one bucket) and never reuse the backup key.

This module is the ONLY place that knows the files live in B2. main.py calls put_object / presigned_get_url /
delete_object and nothing else, so moving to another store later is a change to this file alone.
All calls are blocking; the callers run them in a threadpool.
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("BallotBoxNominationStorage")

PRESIGN_SECONDS = 300          # a download link lives 5 minutes
ENV_NAMES = ("NOMINATION_B2_ENDPOINT", "NOMINATION_B2_KEY_ID",
             "NOMINATION_B2_APPLICATION_KEY", "NOMINATION_B2_BUCKET_NAME")

_client = None


class StorageUnavailable(RuntimeError):
    """The private bucket is not configured or its client could not be created."""


def _cfg() -> dict:
    return {n: (os.getenv(n) or "").strip() for n in ENV_NAMES}


def is_configured() -> bool:
    return all(_cfg().values())


def missing_settings() -> list[str]:
    return [n for n, v in _cfg().items() if not v]


def _bucket() -> str:
    return _cfg()["NOMINATION_B2_BUCKET_NAME"]


def _get_client():
    """Built on first use, so a missing or bad value can never stop the app from booting."""
    global _client
    if _client is not None:
        return _client
    cfg = _cfg()
    if not all(cfg.values()):
        raise StorageUnavailable("Nomination form storage is not configured.")
    try:
        import boto3
        from botocore.config import Config
        _client = boto3.client(
            "s3",
            endpoint_url=cfg["NOMINATION_B2_ENDPOINT"],
            aws_access_key_id=cfg["NOMINATION_B2_KEY_ID"],
            aws_secret_access_key=cfg["NOMINATION_B2_APPLICATION_KEY"],
            config=Config(signature_version="s3v4", retries={"max_attempts": 2, "mode": "standard"},
                          connect_timeout=5, read_timeout=20),
        )
    except Exception as e:
        logger.error(f"Nomination storage client init failed: {e}")
        raise StorageUnavailable("Nomination form storage could not be started.") from e
    return _client


def put_object(key: str, content: bytes, content_type: str) -> None:
    _get_client().put_object(Bucket=_bucket(), Key=key, Body=content, ContentType=content_type)


def _header_safe(name: str) -> str:
    """Filename for the Content-Disposition the link forces: printable ASCII, no quotes or separators."""
    cleaned = re.sub(r'[^A-Za-z0-9._ -]', "_", name or "").strip(" .") or "nomination-form"
    return cleaned[:120]


def presigned_get_url(key: str, filename: str, expires: int = PRESIGN_SECONDS) -> str:
    """Short-lived download link. Forces a download with the original filename instead of rendering inline."""
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{_header_safe(filename)}"'},
        ExpiresIn=max(30, min(int(expires), PRESIGN_SECONDS)),
    )


def delete_object(key: str) -> None:
    _get_client().delete_object(Bucket=_bucket(), Key=key)
