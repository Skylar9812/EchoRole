"""Local-phase bearer identities. Tokens expire when this API process restarts.

No caller-supplied UUID is trusted. Durable authentication is a later boundary.
"""
import secrets
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def issue_identity(request, user_id):
    token = secrets.token_urlsafe(32)
    request.app.state.identities[token] = user_id
    return token


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    user_id = request.app.state.identities.get(credentials.credentials) if credentials else None
    if user_id is None:
        raise HTTPException(401, "Valid bearer identity required", headers={"WWW-Authenticate": "Bearer"})
    return user_id
