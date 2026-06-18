"""
Local/sandbox token endpoint.

The UI's default auth flow POSTs to /api/token and expects {"token": "<jwt>"}.
This branch doesn't otherwise serve that route, so this router mints an RS256 JWT
signed with the backend's private key (the same key whose public half the backend
and UI validate against). Intended for local + sandbox use.

Gated by ENABLE_TOKEN_MINT (default "true") so it can be cleanly turned off when a
real auth/SSO provider issues the token instead. See OAN_HOSTING_PLAN.md.
"""
import os
import time
from typing import Any, Dict

import jwt
from fastapi import APIRouter, Body, HTTPException, status

from app.config import settings
from helpers.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["auth"])

_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "30"))


def _private_key() -> bytes:
    path = settings.base_dir / (settings.jwt_private_key_path or "jwt_private_key.pem")
    with open(path, "rb") as fh:
        return fh.read()


@router.post("/token")
async def issue_token(payload: Dict[str, Any] = Body(default={})):
    """Mint a signed JWT for the UI. Body (e.g. {"metadata": ...}) is not required."""
    try:
        now = int(time.time())
        claims = {
            "sub": "oan-user",
            "name": "OAN User",
            "iat": now,
            "exp": now + _TTL_DAYS * 24 * 3600,
        }
        token = jwt.encode(claims, _private_key(), algorithm=settings.jwt_algorithm)
        return {"token": token}
    except FileNotFoundError:
        logger.error("JWT private key not found; cannot mint token.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token minting not configured (private key missing).",
        )
