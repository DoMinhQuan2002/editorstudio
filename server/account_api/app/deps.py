from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import Device, User, utcnow
from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

SIGNED_IN_ELSEWHERE = {"code": "signed_in_elsewhere",
                       "message": "Tài khoản đã đăng nhập trên máy khác. Bạn đã bị đăng xuất khỏi máy này."}


@dataclass
class CurrentUser:
    user: User
    device: Device


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
                     db: Session = Depends(get_db)) -> CurrentUser:
    if credentials is None:
        raise HTTPException(401, {"code": "not_authenticated", "message": "Bạn cần đăng nhập."})
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, {"code": "token_expired", "message": "Phiên đăng nhập đã hết hạn."})
    except jwt.InvalidTokenError:
        raise HTTPException(401, {"code": "token_invalid", "message": "Phiên đăng nhập không hợp lệ."})

    device = db.get(Device, _uuid(payload.get("did")))
    user = db.get(User, _uuid(payload.get("sub")))
    if user is None or user.status != "active" or device is None or device.user_id != user.id:
        raise HTTPException(401, {"code": "token_invalid", "message": "Phiên đăng nhập không hợp lệ."})
    # One account = one machine: a newer login revoked this device.
    if device.revoked_at is not None:
        raise HTTPException(401, SIGNED_IN_ELSEWHERE)
    device.last_seen_at = utcnow()
    db.commit()
    return CurrentUser(user, device)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _uuid(value):
    import uuid
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
