"""
JWT session handling for BallotBox admin roles.

Design notes for George:
- One token format for all five admin roles (superadmin, it_admin,
  financial_controller, overseer, commission). The `role` claim is what
  main.py's middleware checks.
- Tokens are short-lived (8h default) and carry org_id so a token minted
  for one tenant can't be replayed against another tenant's data even if
  the X-Org-Slug header is swapped.
- JWT_SECRET_KEY has NO default. The app refuses to start without it —
  a hardcoded fallback secret is exactly the kind of thing that ends up
  committed to git and defeats the whole point.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from dotenv import load_dotenv

import jwt
from fastapi import HTTPException, Request

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8 hours

if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. Generate one with `openssl rand -hex 32` "
        "and set it in your environment (.env locally, Render/Railway secrets in prod). "
        "Refusing to start with no secret rather than falling back to a default."
    )

# The five admin roles verify-admin can issue. Voters get their own,
# separate token (see "Voter session tokens" below) whose role is NOT in this
# set, so it can never open an admin route.
ADMIN_ROLES = {"superadmin", "it_admin", "financial_controller", "overseer", "commission"}

# main.py sets this to an async function that checks a token's jti against
# db.revoked_tokens, so a logout (or "revoke all sessions") can invalidate a
# token before its natural expiry. Kept as an injectable hook rather than
# importing db directly here, to avoid a circular import between auth.py and
# main.py.
_revocation_check: Optional[Callable] = None


def set_revocation_check(fn: Callable):
    global _revocation_check
    _revocation_check = fn


def create_access_token(*, subject: str, role: str, org_id: Optional[str], full_name: str = "",
                         scope: str = "full", expire_minutes: Optional[int] = None) -> str:
    """`scope` is "full" for a normal session, or "password_change_only" when the account
    still has must_change_password set — main.py's guard then rejects every path for that
    token except /admin/set-password and /admin/logout, so a temp-password login can't be
    used to touch anything else even if the client never shows the change-password screen.
    `expire_minutes` overrides JWT_EXPIRE_MINUTES for this token only (used to give the
    superadmin a shorter-lived session than the other roles)."""
    if role not in ADMIN_ROLES:
        raise ValueError(f"Unknown admin role: {role}")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,          # student_id / email of the admin, or "superadmin"
        "role": role,
        "org_id": org_id,        # None on single-tenant deployments
        "full_name": full_name,
        "scope": scope,
        "jti": secrets.token_hex(16),  # unique per-token id, used for revocation
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes if expire_minutes is not None else JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Voter session tokens
# ---------------------------------------------------------------------------
# Voters used to be identified at vote time by student_id alone, with the
# server-side flag last_status == "authenticated" as the only proof they'd
# passed the OTP. Anyone who knew a student ID could therefore cast that
# voter's ballot in the window between their OTP and their submit. Now a
# correct OTP also returns a short-lived signed token, and /vote and
# /vote-bulk require it.
#
# Deliberately separate from the admin session layer:
#  - role is "voter", which is NOT in ADMIN_ROLES, so require_admin and the
#    auth guard middleware reject it on every admin route;
#  - it travels in X-Voter-Token, not Authorization, so it can never be
#    mistaken for (or collide with) an admin bearer token;
#  - it is bound to one student_id and one org_id, and to a per-login jti that
#    main.py stores on the voter record, so a fresh OTP login invalidates any
#    earlier token.
VOTER_ROLE = "voter"
VOTER_TOKEN_HEADER = "X-Voter-Token"
VOTER_JWT_EXPIRE_MINUTES = int(os.getenv("VOTER_JWT_EXPIRE_MINUTES", "60"))


def create_voter_token(*, student_id: str, org_id: Optional[str]) -> tuple[str, str]:
    """Returns (token, jti). `student_id` must already be normalized."""
    now = datetime.now(timezone.utc)
    jti = secrets.token_hex(16)
    payload = {
        "sub": student_id,
        "role": VOTER_ROLE,
        "org_id": org_id,
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(minutes=VOTER_JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM), jti


def verify_voter_token(request: Request, student_id: str, org_id: Optional[str]) -> dict:
    """Validate the X-Voter-Token header for this voter and tenant.

    `student_id` must already be normalized. Returns the token payload (the
    caller compares payload["jti"] against the voter record). Raises 401 with a
    message the ballot screen can show as-is.
    """
    expired = HTTPException(
        status_code=401,
        detail="Your voting session has expired. Please verify your identity again.",
    )
    token = request.headers.get(VOTER_TOKEN_HEADER, "").strip()
    if not token:
        raise expired
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:  # includes ExpiredSignatureError
        raise expired

    if (
        payload.get("role") != VOTER_ROLE
        or payload.get("sub") != student_id
        or payload.get("org_id") != org_id
        or not payload.get("jti")
    ):
        raise HTTPException(status_code=403, detail="This voting session does not belong to this voter.")
    return payload


async def decode_access_token(token: str, check_revocation: bool = True) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session. Please log in again.")

    if check_revocation and _revocation_check is not None:
        if await _revocation_check(payload.get("jti")):
            raise HTTPException(status_code=401, detail="Session has been signed out. Please log in again.")

    return payload


def get_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    token = auth_header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return token


async def require_admin(request: Request) -> dict:
    """FastAPI dependency: any authenticated admin, regardless of role.

    Use this directly, or wrap with require_role(...) below for
    role-specific endpoints.
    """
    token = get_bearer_token(request)
    payload = await decode_access_token(token)
    if payload.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized.")
    return payload


def require_role(*roles: str):
    """FastAPI dependency factory for endpoints restricted to specific roles.

    Usage: @app.post(...) async def f(admin: dict = Depends(require_role("superadmin"))):
    """
    allowed = set(roles)

    async def _dep(request: Request) -> dict:
        payload = await require_admin(request)
        if payload["role"] not in allowed:
            raise HTTPException(status_code=403, detail="Not authorized for this action.")
        return payload

    return _dep
