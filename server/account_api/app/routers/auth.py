import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from ..config import get_settings
from ..db import get_db
from ..deps import SIGNED_IN_ELSEWHERE, CurrentUser, client_ip, get_current_user
from ..emailer import send_otp_email
from ..entitlements import entitlements_for
from ..models import Device, EmailOtp, RefreshToken, User, UserIdentity, utcnow
from ..schemas import (DeviceInfo, FacebookLogin, ForgotPassword, GoogleLogin, Message, MeOut, OtpResend,
                       PasswordLogin, RefreshRequest, ResetPassword, Session, SignupStart, SignupVerify, UserOut)
from ..security import (create_access_token, hash_password, hash_secret, new_otp_code, new_refresh_token,
                        same_secret, verify_password)
from ..social import SocialProfile, verify_facebook_token, verify_google_id_token

log = logging.getLogger("mediastudio.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_LOGIN = {"code": "invalid_credentials", "message": "Email hoặc mật khẩu không đúng."}
INVALID_OTP = {"code": "otp_invalid", "message": "Mã xác nhận không đúng hoặc đã hết hạn."}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _norm(email: str) -> str:
    return email.strip().lower()


# ---------------------------------------------------------------- OTP helpers
def _issue_otp(db: DbSession, background: BackgroundTasks, email: str, purpose: str,
               user: User | None, ip: str) -> None:
    settings = get_settings()
    last = db.scalar(select(EmailOtp).where(EmailOtp.email == email, EmailOtp.purpose == purpose)
                     .order_by(EmailOtp.created_at.desc()).limit(1))
    if last and (utcnow() - _aware(last.created_at)).total_seconds() < settings.otp_resend_seconds:
        raise HTTPException(429, {"code": "otp_too_soon",
                                  "message": f"Vui lòng đợi {settings.otp_resend_seconds} giây trước khi gửi lại mã."})
    # Older unused codes for the same purpose stop working.
    db.execute(update(EmailOtp).where(EmailOtp.email == email, EmailOtp.purpose == purpose,
                                      EmailOtp.consumed_at.is_(None)).values(consumed_at=utcnow()))
    code = new_otp_code()
    db.add(EmailOtp(email=email, user_id=user.id if user else None, purpose=purpose, code_hash=hash_secret(code),
                    expires_at=utcnow() + timedelta(minutes=settings.otp_ttl_minutes), request_ip=ip))
    db.commit()
    # Sent before answering so the app can show a clear error if Gmail refuses.
    try:
        send_otp_email(email, code, purpose, settings.otp_ttl_minutes)
    except Exception as exc:
        log.exception("Sending OTP e-mail to %s failed", email)
        raise HTTPException(502, {"code": "email_send_failed",
                                  "message": f"Không gửi được email xác nhận: {type(exc).__name__}: {exc}"})


def _consume_otp(db: DbSession, email: str, purpose: str, code: str) -> None:
    otp = db.scalar(select(EmailOtp).where(EmailOtp.email == email, EmailOtp.purpose == purpose,
                                           EmailOtp.consumed_at.is_(None))
                    .order_by(EmailOtp.created_at.desc()).limit(1))
    if otp is None or _aware(otp.expires_at) <= utcnow() or otp.attempts >= get_settings().otp_max_attempts:
        raise HTTPException(400, INVALID_OTP)
    if not same_secret(code, otp.code_hash):
        otp.attempts += 1
        db.commit()
        raise HTTPException(400, INVALID_OTP)
    otp.consumed_at = utcnow()


# ---------------------------------------------------------------- sessions
def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name, avatar_url=user.avatar_url,
                   email_verified=user.email_verified, providers=sorted(i.provider for i in user.identities))


def _start_session(db: DbSession, user: User, info: DeviceInfo) -> Session:
    """Signs the user in on this machine and signs every other machine out."""
    now = utcnow()
    db.execute(update(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None),
                                    Device.device_key != info.device_key)
               .values(revoked_at=now, revoke_reason="signed_in_elsewhere"))
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now))
    db.flush()

    device = db.scalar(select(Device).where(Device.user_id == user.id, Device.device_key == info.device_key))
    if device is None:
        device = Device(user_id=user.id, device_key=info.device_key)
        db.add(device)
    device.device_name, device.os, device.app_version = info.device_name, info.os, info.app_version
    device.revoked_at, device.revoke_reason, device.last_seen_at = None, None, now
    user.last_login_at = now
    db.flush()

    refresh = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, device_id=device.id, token_hash=hash_secret(refresh),
                        expires_at=now + timedelta(days=get_settings().refresh_token_days)))
    db.commit()
    db.refresh(user)
    access, lifetime = create_access_token(user.id, device.id)
    return Session(access_token=access, expires_in=lifetime, refresh_token=refresh,
                   user=_user_out(user), entitlements=entitlements_for(db, user))


def _ensure_identity(db: DbSession, user: User, provider: str, provider_user_id: str, email: str | None) -> None:
    identity = db.scalar(select(UserIdentity).where(UserIdentity.user_id == user.id, UserIdentity.provider == provider))
    if identity is None:
        db.add(UserIdentity(user_id=user.id, provider=provider, provider_user_id=provider_user_id,
                            provider_email=email, last_used_at=utcnow()))
    else:
        identity.last_used_at = utcnow()


# ---------------------------------------------------------------- email sign-up
@router.post("/signup/start", response_model=Message)
def signup_start(body: SignupStart, request: Request, background: BackgroundTasks, db: DbSession = Depends(get_db)):
    email = _norm(body.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.status != "pending":
        raise HTTPException(409, {"code": "email_taken", "message": "Email này đã có tài khoản. Hãy đăng nhập."})
    if user is None:
        user = User(email=email, status="pending")
        db.add(user)
    user.password_hash = hash_password(body.password)
    user.display_name = body.display_name or email.split("@")[0]
    db.flush()
    _issue_otp(db, background, email, "signup", user, client_ip(request))
    return Message(message="Đã gửi mã xác nhận đến email của bạn.")


@router.post("/signup/verify", response_model=Session)
def signup_verify(body: SignupVerify, db: DbSession = Depends(get_db)):
    email = _norm(body.email)
    user = db.scalar(select(User).where(User.email == email, User.status == "pending"))
    if user is None:
        raise HTTPException(400, INVALID_OTP)
    _consume_otp(db, email, "signup", body.code)
    user.status, user.email_verified = "active", True
    _ensure_identity(db, user, "email", email, email)
    db.flush()
    return _start_session(db, user, body.device)


@router.post("/otp/resend", response_model=Message)
def otp_resend(body: OtpResend, request: Request, background: BackgroundTasks, db: DbSession = Depends(get_db)):
    email = _norm(body.email)
    wanted = "pending" if body.purpose == "signup" else "active"
    user = db.scalar(select(User).where(User.email == email, User.status == wanted))
    if user is not None:
        _issue_otp(db, background, email, body.purpose, user, client_ip(request))
    # Same answer either way so the endpoint does not reveal which emails have accounts.
    return Message(message="Nếu email hợp lệ, mã mới đã được gửi.")


# ---------------------------------------------------------------- password login / reset
@router.post("/login", response_model=Session)
def login(body: PasswordLogin, db: DbSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == _norm(body.email)))
    if user is None or user.status != "active" or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, INVALID_LOGIN)
    _ensure_identity(db, user, "email", user.email, user.email)
    return _start_session(db, user, body.device)


@router.post("/password/forgot", response_model=Message)
def password_forgot(body: ForgotPassword, request: Request, background: BackgroundTasks,
                    db: DbSession = Depends(get_db)):
    email = _norm(body.email)
    user = db.scalar(select(User).where(User.email == email, User.status == "active"))
    if user is not None:
        _issue_otp(db, background, email, "reset_password", user, client_ip(request))
    return Message(message="Nếu email có tài khoản, mã đặt lại mật khẩu đã được gửi.")


@router.post("/password/reset", response_model=Message)
def password_reset(body: ResetPassword, db: DbSession = Depends(get_db)):
    email = _norm(body.email)
    user = db.scalar(select(User).where(User.email == email, User.status == "active"))
    if user is None:
        raise HTTPException(400, INVALID_OTP)
    _consume_otp(db, email, "reset_password", body.code)
    user.password_hash = hash_password(body.new_password)
    # Sign out everywhere after a password change.
    now = utcnow()
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now))
    db.execute(update(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None))
               .values(revoked_at=now, revoke_reason="password_reset"))
    db.commit()
    return Message(message="Đã đổi mật khẩu. Hãy đăng nhập lại.")


# ---------------------------------------------------------------- Google / Facebook
def _social_login(db: DbSession, profile: SocialProfile, device: DeviceInfo) -> Session:
    identity = db.scalar(select(UserIdentity).where(UserIdentity.provider == profile.provider,
                                                    UserIdentity.provider_user_id == profile.provider_user_id))
    if identity is not None:
        user = db.get(User, identity.user_id)
        identity.last_used_at = utcnow()
    else:
        if not profile.email or not profile.email_verified:
            raise HTTPException(400, {"code": "email_required",
                                      "message": "Tài khoản này không cung cấp email đã xác minh. Hãy đăng ký bằng email."})
        email = _norm(profile.email)
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, email_verified=True, status="active", display_name=profile.name,
                        avatar_url=profile.avatar_url)
            db.add(user)
            db.flush()
        elif user.status == "pending":   # unfinished e-mail sign-up; the provider verified the address
            user.status, user.email_verified = "active", True
        db.add(UserIdentity(user_id=user.id, provider=profile.provider, provider_user_id=profile.provider_user_id,
                            provider_email=email, last_used_at=utcnow()))
    if user is None or user.status != "active":
        raise HTTPException(403, {"code": "account_locked", "message": "Tài khoản đang bị khóa."})
    user.avatar_url = user.avatar_url or profile.avatar_url
    user.display_name = user.display_name or profile.name
    db.flush()
    return _start_session(db, user, device)


@router.post("/google", response_model=Session)
def login_google(body: GoogleLogin, db: DbSession = Depends(get_db)):
    return _social_login(db, verify_google_id_token(body.id_token), body.device)


@router.post("/facebook", response_model=Session)
def login_facebook(body: FacebookLogin, db: DbSession = Depends(get_db)):
    return _social_login(db, verify_facebook_token(body.access_token), body.device)


# ---------------------------------------------------------------- refresh / logout / me
@router.post("/refresh", response_model=Session)
def refresh(body: RefreshRequest, db: DbSession = Depends(get_db)):
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_secret(body.refresh_token)))
    device = db.get(Device, token.device_id) if token and token.device_id else None
    if token is None or device is None or device.device_key != body.device_key:
        raise HTTPException(401, {"code": "token_invalid", "message": "Phiên đăng nhập không hợp lệ."})
    if device.revoked_at is not None:
        raise HTTPException(401, SIGNED_IN_ELSEWHERE if device.revoke_reason == "signed_in_elsewhere"
                            else {"code": "signed_out", "message": "Bạn đã bị đăng xuất. Hãy đăng nhập lại."})
    if token.revoked_at is not None or _aware(token.expires_at) <= utcnow():
        raise HTTPException(401, {"code": "token_expired", "message": "Phiên đăng nhập đã hết hạn."})

    user = db.get(User, token.user_id)
    new_value = new_refresh_token()
    new_token = RefreshToken(user_id=user.id, device_id=device.id, token_hash=hash_secret(new_value),
                             expires_at=utcnow() + timedelta(days=get_settings().refresh_token_days))
    db.add(new_token)
    db.flush()
    token.revoked_at, token.replaced_by = utcnow(), new_token.id
    device.last_seen_at = utcnow()
    db.commit()
    db.refresh(user)
    access, lifetime = create_access_token(user.id, device.id)
    return Session(access_token=access, expires_in=lifetime, refresh_token=new_value,
                   user=_user_out(user), entitlements=entitlements_for(db, user))


@router.post("/logout", response_model=Message)
def logout(current: CurrentUser = Depends(get_current_user), db: DbSession = Depends(get_db)):
    now = utcnow()
    db.execute(update(RefreshToken).where(RefreshToken.device_id == current.device.id,
                                          RefreshToken.revoked_at.is_(None)).values(revoked_at=now))
    device = db.get(Device, current.device.id)
    device.revoked_at, device.revoke_reason = now, "logout"
    db.commit()
    return Message(message="Đã đăng xuất.")


me_router = APIRouter(tags=["account"])


@me_router.get("/me", response_model=MeOut)
def me(current: CurrentUser = Depends(get_current_user), db: DbSession = Depends(get_db)):
    user = db.get(User, current.user.id)
    return MeOut(user=_user_out(user), entitlements=entitlements_for(db, user))
