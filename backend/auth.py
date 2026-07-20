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
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, Request

JWT_SECRET = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8 hours

if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. Generate one with `openssl rand -hex 32` "
        "and set it in your environment (.env locally, Render/Railway secrets in prod). "
        "Refusing to start with no secret rather than falling back to a default."
    )

# The five admin roles verify-admin can issue. Voters never get a token —
# they authenticate per-request via student_id + OTP, which is unrelated
# to this session layer.
ADMIN_ROLES = {"superadmin", "it_admin", "financial_controller", "overseer", "commission"}


def create_access_token(*, subject: str, role: str, org_id: Optional[str], full_name: str = "") -> str:
    if role not in ADMIN_ROLES:
        raise ValueError(f"Unknown admin role: {role}")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,          # student_id / email of the admin, or "superadmin"
        "role": role,
        "org_id": org_id,        # None on single-tenant deployments
        "full_name": full_name,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session. Please log in again.")


def get_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    token = auth_header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return token


def require_admin(request: Request) -> dict:
    """FastAPI dependency: any authenticated admin, regardless of role.

    Use this directly, or wrap with require_role(...) below for
    role-specific endpoints.
    """
    token = get_bearer_token(request)
    payload = decode_access_token(token)
    if payload.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized.")
    return payload


def require_role(*roles: str):
    """FastAPI dependency factory for endpoints restricted to specific roles.

    Usage: @app.post(...) async def f(admin: dict = Depends(require_role("superadmin"))):
    """
    allowed = set(roles)

    def _dep(request: Request) -> dict:
        payload = require_admin(request)
        if payload["role"] not in allowed:
            raise HTTPException(status_code=403, detail="Not authorized for this action.")
        return payload

    return _dep
