"""Replaceable local-development signed bearer identities, not account authentication."""
import base64
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import tempfile
import time
import uuid

import database as db
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

TOKEN_LIFETIME = 30 * 24 * 60 * 60
bearer = HTTPBearer(auto_error=False)


def load_signing_key():
    configured = os.environ.get("ECHOROLE_IDENTITY_SECRET")
    if configured is not None:
        if len(configured.encode()) < 32:
            raise RuntimeError("ECHOROLE_IDENTITY_SECRET must contain at least 32 bytes")
        return configured.encode()
    path = Path(db.DB_NAME + ".identity-key")
    if not path.exists():
        # Publish a complete key atomically. Simultaneous workers all load the
        # winning file; an exclusive create followed by write would race readers.
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(secrets.token_bytes(32))
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    key = path.read_bytes()
    if len(key) != 32:
        raise RuntimeError("Invalid local identity signing key")
    return key


def issue_identity(request, user_id):
    payload = f"v1.{user_id}.{int(time.time()) + TOKEN_LIFETIME}.{secrets.token_hex(16)}"
    signature = hmac.new(request.app.state.identity_key, payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    try:
        if credentials is None:
            raise ValueError()
        version, user_id, expiry, nonce, signature = credentials.credentials.split(".")
        payload = f"{version}.{user_id}.{expiry}.{nonce}"
        expected = base64.urlsafe_b64encode(hmac.new(
            request.app.state.identity_key, payload.encode(), hashlib.sha256
        ).digest()).decode().rstrip("=")
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        if version != "v1" or str(uuid.UUID(user_id)) != user_id or int(expiry) <= time.time():
            raise ValueError()
        if not db.get_user_profile(user_id)["updated_at"]:
            raise ValueError()
        return user_id
    except (ValueError, TypeError):
        raise HTTPException(401, "Valid bearer identity required", headers={"WWW-Authenticate": "Bearer"}) from None
