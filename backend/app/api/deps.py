"""Auth dependencies — single-user bearer-token model + coach service token."""
from __future__ import annotations

import hashlib
import hmac
import secrets

import itsdangerous
from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import get_db
from ..services import settings as settings_svc

_bearer = HTTPBearer(auto_error=False)
_signer = itsdangerous.URLSafeTimedSerializer(get_config().app_secret, salt="pentrain-auth")

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(pw: str) -> str:
    """scrypt with a per-password salt — memory-hard, stdlib-only."""
    salt = secrets.token_hex(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt.encode(),
                        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${salt}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    """Constant-time verify; accepts the scrypt$ format only."""
    try:
        _fmt, n, salt, hexhash = stored.split("$", 3)
        if _fmt != "scrypt":
            return False
        dk = hashlib.scrypt(pw.encode(), salt=salt.encode(),
                            n=int(n), r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
        return hmac.compare_digest(dk.hex(), hexhash)
    except (ValueError, TypeError):
        return False


def make_token() -> str:
    return _signer.dumps({"u": "admin", "n": secrets.token_hex(8)})


def verify_token(token: str) -> bool:
    try:
        _signer.loads(token, max_age=30 * 24 * 3600)
        return True
    except itsdangerous.BadSignature:
        return False


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> str:
    if creds and verify_token(creds.credentials):
        return "admin"
    # bootstrap: no password set yet → allow (setup wizard will set one)
    stored = await settings_svc.get_secret(db, "security.admin_token_hash")
    if not stored:
        return "admin"
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token")


async def require_coach(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Service-token auth for the coach container's internal API."""
    if creds and secrets.compare_digest(creds.credentials, get_config().coach_service_token):
        return "coach"
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid service token")


async def ws_auth(ws: WebSocket, db: AsyncSession) -> bool:
    token = ws.query_params.get("token")
    if token and verify_token(token):
        return True
    stored = await settings_svc.get_secret(db, "security.admin_token_hash")
    if not stored:
        return True
    await ws.close(code=4401)
    return False
