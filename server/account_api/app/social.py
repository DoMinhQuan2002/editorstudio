"""Verifies tokens from Google and Facebook sign-in done in the desktop app.

Google: the app runs the OAuth "Desktop app" flow (system browser + loopback redirect, PKCE)
and sends the resulting id_token here.
Facebook: the app runs Facebook Login and sends the user access token here.
"""
from dataclasses import dataclass

import httpx
from fastapi import HTTPException

from .config import get_settings


@dataclass
class SocialProfile:
    provider: str
    provider_user_id: str
    email: str | None
    email_verified: bool
    name: str | None
    avatar_url: str | None


def verify_google_id_token(id_token: str) -> SocialProfile:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    client_ids = get_settings().google_client_id_list
    if not client_ids:
        raise HTTPException(503, {"code": "google_not_configured", "message": "Chưa cấu hình đăng nhập Google."})
    try:
        info = google_id_token.verify_oauth2_token(id_token, google_requests.Request())
    except ValueError as exc:
        raise HTTPException(401, {"code": "google_token_invalid", "message": "Phiên đăng nhập Google không hợp lệ."}) from exc
    if info.get("aud") not in client_ids:
        raise HTTPException(401, {"code": "google_token_invalid", "message": "Token Google không dành cho ứng dụng này."})
    return SocialProfile("google", info["sub"], info.get("email"), bool(info.get("email_verified")),
                         info.get("name"), info.get("picture"))


def verify_facebook_token(access_token: str) -> SocialProfile:
    settings = get_settings()
    if not settings.facebook_app_id or not settings.facebook_app_secret:
        raise HTTPException(503, {"code": "facebook_not_configured", "message": "Chưa cấu hình đăng nhập Facebook."})
    app_token = f"{settings.facebook_app_id}|{settings.facebook_app_secret}"
    with httpx.Client(timeout=10) as client:
        debug = client.get("https://graph.facebook.com/debug_token",
                           params={"input_token": access_token, "access_token": app_token}).json().get("data", {})
        if not debug.get("is_valid") or str(debug.get("app_id")) != settings.facebook_app_id:
            raise HTTPException(401, {"code": "facebook_token_invalid", "message": "Phiên đăng nhập Facebook không hợp lệ."})
        me = client.get("https://graph.facebook.com/me",
                        params={"fields": "id,name,email,picture.type(large)", "access_token": access_token}).json()
    picture = (me.get("picture") or {}).get("data", {}).get("url")
    # Facebook only returns emails it has confirmed.
    return SocialProfile("facebook", str(me["id"]), me.get("email"), bool(me.get("email")), me.get("name"), picture)
