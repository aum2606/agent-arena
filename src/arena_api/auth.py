import os
import re
import secrets
from collections.abc import Iterator
from typing import Annotated
from urllib.parse import urlencode

import httpx2
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from arena_api import accounts
from arena_api.accounts import User

router = APIRouter(prefix="/auth")

SESSION_COOKIE = "arena_session"
STATE_COOKIE = "arena_oauth_state"
STATE_SECONDS = 600
GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"
HANDLE = re.compile(r"[A-Za-z0-9_-]{1,39}")


def public_url() -> str:
    """Where browsers reach the web app; GitHub sends them back to it."""
    return os.environ.get("PUBLIC_URL", "http://127.0.0.1:3100").rstrip("/")


def _github_settings() -> tuple[str, str]:
    id_, secret = os.environ.get("GITHUB_CLIENT_ID"), os.environ.get("GITHUB_CLIENT_SECRET")
    if not id_ or not secret:
        raise HTTPException(
            status_code=503,
            detail="GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET are not set (see .env.example)",
        )
    return id_, secret


def dev_login_enabled() -> bool:
    return os.environ.get("ARENA_DEV_LOGIN") == "1"


def get_github_http() -> Iterator[httpx2.Client]:
    with httpx2.Client(timeout=10.0) as client:
        yield client


def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=public_url().startswith("https://"),
        path="/",
    )


def _start_session(response: Response, user: User) -> None:
    _set_cookie(
        response, SESSION_COOKIE, accounts.create_session(user.id), accounts.SESSION_DAYS * 86400
    )


def current_user(token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None) -> User:
    user = accounts.user_for_token(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="sign in first")
    return user


@router.get("/config")
def config() -> dict[str, bool]:
    return {"github": bool(os.environ.get("GITHUB_CLIENT_ID")), "dev_login": dev_login_enabled()}


@router.get("/me")
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@router.get("/github/login")
def github_login() -> RedirectResponse:
    client_id, _ = _github_settings()
    state = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": f"{public_url()}/api/auth/github/callback",
            "state": state,
        }
    )
    response = RedirectResponse(f"{GITHUB_AUTHORIZE}?{query}")
    _set_cookie(response, STATE_COOKIE, state, STATE_SECONDS)
    return response


@router.get("/github/callback")
def github_callback(
    code: str,
    state: str,
    http: Annotated[httpx2.Client, Depends(get_github_http)],
    remembered: Annotated[str | None, Cookie(alias=STATE_COOKIE)] = None,
) -> RedirectResponse:
    # The state we set before leaving must come back unchanged, or someone else started this login.
    if not remembered or not state or not secrets.compare_digest(state, remembered):
        raise HTTPException(status_code=400, detail="sign-in state did not match; try again")
    client_id, client_secret = _github_settings()
    try:
        exchanged = http.post(
            GITHUB_TOKEN,
            data={"client_id": client_id, "client_secret": client_secret, "code": code},
            headers={"Accept": "application/json"},
        ).json()
        token = exchanged.get("access_token")
        if not token:
            raise HTTPException(status_code=400, detail="GitHub did not accept the sign-in code")
        profile = http.get(GITHUB_USER, headers={"Authorization": f"Bearer {token}"}).json()
        user = accounts.upsert_user("github", str(profile["id"]), profile["login"])
    except (httpx2.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="could not reach GitHub to sign in") from exc
    response = RedirectResponse("/")
    response.delete_cookie(STATE_COOKIE, path="/")
    _start_session(response, user)
    return response


class DevLogin(BaseModel):
    handle: str


@router.post("/dev", status_code=204)
def dev_login(body: DevLogin) -> Response:
    """Local development only: sign in as any handle, no GitHub. Off unless ARENA_DEV_LOGIN=1."""
    if not dev_login_enabled():
        raise HTTPException(status_code=404, detail="not found")
    if not HANDLE.fullmatch(body.handle):
        raise HTTPException(status_code=422, detail="handle must be 1-39 letters, digits, _ or -")
    response = Response(status_code=204)
    _start_session(response, accounts.upsert_user("dev", body.handle, body.handle))
    return response


@router.post("/logout", status_code=204)
def logout(token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None) -> Response:
    if token:
        accounts.end_session(token)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
