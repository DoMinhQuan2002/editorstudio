from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, engine, get_db
from ..models import (
    AdminAccount,
    AdminAuditLog,
    AspectRatio,
    AudioTrack,
    Device,
    Feature,
    Payment,
    Plan,
    PlanFeature,
    PlanPrice,
    RefreshToken,
    Subscription,
    Template,
    TemplateAsset,
    TemplateCategory,
    TemplateVersion,
    TemplateVersionAspect,
    UsageEvent,
    User,
    UserIdentity,
    utcnow,
)
from ..security import hash_password, verify_password

router = APIRouter(prefix="/admin/api", tags=["admin"])
COOKIE_NAME = "ms_admin_session"
JWT_ALGORITHM = "HS256"
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCK_MINUTES = 15


def ensure_admin_schema() -> None:
    # Additive upgrade only: preserve existing account, billing, and template rows.
    TemplateCategory.__table__.create(bind=engine, checkfirst=True)
    AspectRatio.__table__.create(bind=engine, checkfirst=True)
    AudioTrack.__table__.create(bind=engine, checkfirst=True)
    Template.__table__.create(bind=engine, checkfirst=True)
    AdminAccount.__table__.create(bind=engine, checkfirst=True)
    TemplateVersion.__table__.create(bind=engine, checkfirst=True)
    TemplateVersionAspect.__table__.create(bind=engine, checkfirst=True)
    TemplateAsset.__table__.create(bind=engine, checkfirst=True)
    UsageEvent.__table__.create(bind=engine, checkfirst=True)
    AdminAuditLog.__table__.create(bind=engine, checkfirst=True)

    existing_columns = {column["name"] for column in inspect(engine).get_columns("templates")}
    additions = {
        "description": "TEXT",
        "category_id": "INTEGER REFERENCES template_categories(id) ON DELETE SET NULL",
        "sort_order": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TIMESTAMP WITH TIME ZONE",
        "updated_at": "TIMESTAMP WITH TIME ZONE",
    }
    with engine.begin() as connection:
        for name, sql_type in additions.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE templates ADD COLUMN {name} {sql_type}"))
        connection.execute(
            text("UPDATE templates SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
                 "updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)")
        )
        admin_columns = {column["name"] for column in inspect(connection).get_columns("admin_accounts")}
        if "session_version" not in admin_columns:
            connection.execute(text("ALTER TABLE admin_accounts ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0"))


class AdminLogin(BaseModel):
    # Admin identities may use a local-only domain such as .mediastudio.local.
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=128)


class AdminPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=72)


class UserStatusChange(BaseModel):
    status: str = Field(pattern="^(active|locked)$")
    reason: str = Field(min_length=3, max_length=300)


class PlanChange(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class PriceChange(BaseModel):
    amount: Decimal | None = Field(default=None, ge=0, le=999999999)
    is_active: bool | None = None


class PlanFeatureChange(BaseModel):
    feature_codes: list[str] = Field(max_length=100)


class TemplateChange(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category_id: int | None = Field(default=None, ge=1)
    is_premium: bool | None = None
    status: str | None = Field(default=None, pattern="^(draft|published|retired)$")


class TemplateCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category_id: int | None = Field(default=None, ge=1)
    output_kind: str = Field(pattern="^(video|image)$")
    is_premium: bool = False
    status: str = Field(default="draft", pattern="^(draft|published|retired)$")


class CategoryCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern="^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=80)
    icon: str | None = Field(default=None, max_length=40)
    sort_order: int = Field(default=0, ge=0, le=10000)


class AudioTrackCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    artist: str | None = Field(default=None, max_length=160)
    duration_ms: int = Field(ge=1, le=3600000)
    file_url: str = Field(min_length=1, max_length=2000)
    file_sha256: str = Field(pattern="^[a-fA-F0-9]{64}$")
    bpm: Decimal | None = Field(default=None, ge=0, le=9999)
    license: str = Field(pattern="^(owned|royalty_free|licensed)$")
    license_note: str | None = Field(default=None, max_length=2000)
    beat_markers: list[int] | None = None


class TemplateVersionCreate(BaseModel):
    template_id: uuid.UUID
    version: str = Field(min_length=1, max_length=40)
    definition: dict
    min_app_version: str | None = Field(default=None, max_length=20)
    default_audio_id: uuid.UUID | None = None
    duration_ms: int | None = Field(default=None, ge=1)
    page_count: int | None = Field(default=None, ge=1)
    min_media: int = Field(default=1, ge=0, le=1000)
    max_media: int = Field(ge=1, le=1000)
    is_current: bool = False


class TemplateAssetCreate(BaseModel):
    template_version_id: uuid.UUID
    kind: str = Field(pattern="^(poster|preview_video|font|sticker|overlay|other)$")
    aspect_code: str | None = Field(default=None, max_length=10)
    file_url: str = Field(min_length=1, max_length=2000)
    file_sha256: str = Field(pattern="^[a-fA-F0-9]{64}$")
    byte_size: int = Field(ge=0, le=2**63 - 1)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _admin_token(admin: AdminAccount) -> tuple[str, int]:
    settings = get_settings()
    lifetime = settings.access_token_minutes * 60
    now = _now_utc()
    token = jwt.encode(
        {
            "sub": str(admin.id),
            "role": admin.role,
            "ver": admin.session_version,
            "iat": now,
            "exp": now + timedelta(seconds=lifetime),
            "typ": "admin_access",
        },
        settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    return token, lifetime


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> AdminAccount:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, {"code": "admin_not_authenticated", "message": "Vui lòng đăng nhập quản trị."})
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM])
        if payload.get("typ") != "admin_access":
            raise jwt.InvalidTokenError("wrong token type")
        admin_id = uuid.UUID(str(payload.get("sub")))
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(401, {"code": "admin_session_invalid", "message": "Phiên quản trị đã hết hạn."})

    admin = db.get(AdminAccount, admin_id)
    if admin is None or admin.status != "active":
        raise HTTPException(401, {"code": "admin_session_invalid", "message": "Tài khoản quản trị không còn hoạt động."})
    if payload.get("ver") != admin.session_version:
        raise HTTPException(401, {"code": "admin_session_invalid", "message": "Phiên quản trị đã bị thu hồi."})
    return admin


def get_ready_admin(admin: AdminAccount = Depends(get_current_admin)) -> AdminAccount:
    if admin.must_change_password:
        raise HTTPException(428, {"code": "password_change_required", "message": "Hãy đổi mật khẩu tạm trước khi tiếp tục."})
    return admin


def _super_admin(admin: AdminAccount) -> None:
    if admin.role != "super_admin":
        raise HTTPException(403, {"code": "admin_forbidden", "message": "Thao tác này chỉ dành cho quản trị viên cấp cao."})


def _audit(
    db: Session,
    admin: AdminAccount,
    request: Request,
    action: str,
    entity_type: str,
    entity_id: str | None,
    details: dict | None = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip_address = forwarded.split(",", 1)[0].strip() if forwarded else (request.client.host if request.client else None)
    db.add(
        AdminAuditLog(
            admin_id=admin.id,
            admin_email=admin.email,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address,
        )
    )


def _admin_out(admin: AdminAccount) -> dict:
    return {
        "id": str(admin.id),
        "email": admin.email,
        "display_name": admin.display_name,
        "role": admin.role,
        "must_change_password": admin.must_change_password,
    }


@router.post("/auth/login")
def admin_login(body: AdminLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    admin = db.scalar(select(AdminAccount).where(func.lower(AdminAccount.email) == email))
    if admin is None or admin.status != "active":
        raise HTTPException(401, {"code": "invalid_credentials", "message": "Email hoặc mật khẩu không đúng."})

    locked_until = _aware(admin.locked_until)
    now = _now_utc()
    if locked_until and locked_until > now:
        raise HTTPException(429, {"code": "admin_temporarily_locked", "message": "Tài khoản tạm khóa do nhập sai nhiều lần. Hãy thử lại sau."})

    if not verify_password(body.password, admin.password_hash):
        admin.failed_login_attempts += 1
        if admin.failed_login_attempts >= LOGIN_FAILURE_LIMIT:
            admin.failed_login_attempts = 0
            admin.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
        db.commit()
        raise HTTPException(401, {"code": "invalid_credentials", "message": "Email hoặc mật khẩu không đúng."})

    admin.failed_login_attempts = 0
    admin.locked_until = None
    admin.last_login_at = now
    token, lifetime = _admin_token(admin)
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=lifetime,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/admin/api",
    )
    with SessionLocal() as audit_db:
        persisted_admin = audit_db.get(AdminAccount, admin.id)
        if persisted_admin:
            _audit(audit_db, persisted_admin, request, "admin.login", "admin_account", str(admin.id))
            audit_db.commit()
    return {"admin": _admin_out(admin)}


@router.post("/auth/logout")
def admin_logout(response: Response, request: Request, admin: AdminAccount | None = Depends(get_current_admin), db: Session = Depends(get_db)):
    if admin:
        _audit(db, admin, request, "admin.logout", "admin_account", str(admin.id))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/admin/api", samesite="strict")
    return {"ok": True}


@router.get("/auth/session")
def admin_session(admin: AdminAccount = Depends(get_current_admin)):
    return {"admin": _admin_out(admin)}


@router.post("/auth/change-password")
def change_admin_password(
    body: AdminPasswordChange,
    request: Request,
    response: Response,
    admin: AdminAccount = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, admin.password_hash):
        raise HTTPException(400, {"code": "current_password_invalid", "message": "Mật khẩu hiện tại không đúng."})
    if body.current_password == body.new_password:
        raise HTTPException(400, {"code": "password_unchanged", "message": "Mật khẩu mới cần khác mật khẩu hiện tại."})
    admin.password_hash = hash_password(body.new_password)
    admin.must_change_password = False
    admin.session_version += 1
    admin.failed_login_attempts = 0
    admin.locked_until = None
    _audit(db, admin, request, "admin.password_changed", "admin_account", str(admin.id))
    db.commit()
    token, lifetime = _admin_token(admin)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=lifetime,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/admin/api",
    )
    return {"ok": True, "admin": _admin_out(admin)}


@router.get("/overview")
def overview(admin: AdminAccount = Depends(get_ready_admin), db: Session = Depends(get_db)):
    now = utcnow()
    since = now - timedelta(days=30)
    user_total = db.scalar(select(func.count(User.id))) or 0
    active_users = db.scalar(select(func.count(User.id)).where(User.status == "active", User.deleted_at.is_(None))) or 0
    unverified_users = db.scalar(select(func.count(User.id)).where(User.email_verified.is_(False), User.deleted_at.is_(None))) or 0
    locked_users = db.scalar(select(func.count(User.id)).where(User.status == "locked")) or 0
    active_pro = db.scalar(
        select(func.count(distinct(Subscription.user_id)))
        .join(PlanPrice, Subscription.plan_price_id == PlanPrice.id)
        .join(Plan, PlanPrice.plan_id == Plan.id)
        .where(Plan.code == "pro", Subscription.status == "active", Subscription.current_period_end > now)
    ) or 0
    revenue = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == "succeeded", Payment.paid_at >= since
        )
    ) or Decimal("0")
    paid_count = db.scalar(
        select(func.count(Payment.id)).where(Payment.status == "succeeded", Payment.paid_at >= since)
    ) or 0
    pending_payments = db.scalar(select(func.count(Payment.id)).where(Payment.status == "pending")) or 0
    template_total = db.scalar(select(func.count(Template.id))) or 0
    published_templates = db.scalar(select(func.count(Template.id)).where(Template.status == "published")) or 0

    recent_users = db.scalars(select(User).order_by(User.created_at.desc()).limit(5)).all()
    recent_payments = db.execute(
        select(Payment, User, Plan, PlanPrice)
        .join(User, Payment.user_id == User.id)
        .join(PlanPrice, Payment.plan_price_id == PlanPrice.id)
        .join(Plan, PlanPrice.plan_id == Plan.id)
        .order_by(Payment.created_at.desc())
        .limit(5)
    ).all()

    series_start = now - timedelta(days=13)
    day_keys = [(now.date() - timedelta(days=offset)).isoformat() for offset in range(13, -1, -1)]
    series = {key: {"date": key, "signups": 0, "successful_payments": 0} for key in day_keys}
    signup_dates = db.scalars(select(User.created_at).where(User.created_at >= series_start)).all()
    for created_at in signup_dates:
        key = _aware(created_at).date().isoformat()
        if key in series:
            series[key]["signups"] += 1
    paid_dates = db.scalars(
        select(Payment.paid_at).where(Payment.status == "succeeded", Payment.paid_at >= series_start)
    ).all()
    for paid_at in paid_dates:
        key = _aware(paid_at).date().isoformat()
        if key in series:
            series[key]["successful_payments"] += 1

    schema = inspect(db.get_bind())
    usage_available = schema.has_table("usage_events")
    usage_count = None
    if usage_available:
        usage_count = db.execute(
            text("SELECT COUNT(*) FROM usage_events WHERE created_at >= :since"), {"since": since}
        ).scalar() or 0

    return {
        "metrics": {
            "users_total": user_total,
            "users_active": active_users,
            "users_unverified": unverified_users,
            "users_locked": locked_users,
            "active_pro": active_pro,
            "revenue_30d": str(revenue),
            "payments_succeeded_30d": paid_count,
            "payments_pending": pending_payments,
            "templates_total": template_total,
            "templates_published": published_templates,
            "template_usage_30d": usage_count,
        },
        "usage_tracking_available": usage_available,
        "daily_activity": list(series.values()),
        "recent_users": [
            {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "status": user.status,
                "email_verified": user.email_verified,
                "created_at": user.created_at,
            }
            for user in recent_users
        ],
        "recent_payments": [
            {
                "id": str(payment.id),
                "txn_ref": payment.vnp_txn_ref,
                "email": user.email,
                "plan": plan.name,
                "billing_period": price.billing_period,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "status": payment.status,
                "created_at": payment.created_at,
            }
            for payment, user, plan, price in recent_payments
        ],
    }


@router.get("/users")
def list_users(
    q: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    query = select(User).where(User.deleted_at.is_(None))
    if q:
        needle = f"%{q.strip()}%"
        query = query.where(or_(User.email.ilike(needle), User.display_name.ilike(needle)))
    if status:
        query = query.where(User.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = db.scalars(query.order_by(User.created_at.desc()).offset(offset).limit(limit)).all()
    user_ids = [user.id for user in users]

    subscriptions: dict[uuid.UUID, dict] = {}
    if user_ids:
        rows = db.execute(
            select(Subscription.user_id, Plan.code, Plan.name, Subscription.current_period_end)
            .join(PlanPrice, Subscription.plan_price_id == PlanPrice.id)
            .join(Plan, PlanPrice.plan_id == Plan.id)
            .where(
                Subscription.user_id.in_(user_ids),
                Subscription.status == "active",
                Subscription.current_period_end > utcnow(),
            )
            .order_by(Subscription.current_period_end.desc())
        ).all()
        for user_id, code, name, end in rows:
            subscriptions.setdefault(user_id, {"code": code, "name": name, "ends_at": end})

    devices: dict[uuid.UUID, dict] = {}
    if user_ids:
        rows = db.scalars(
            select(Device)
            .where(Device.user_id.in_(user_ids), Device.revoked_at.is_(None))
            .order_by(Device.last_seen_at.desc())
        ).all()
        for device in rows:
            devices.setdefault(
                device.user_id,
                {"name": device.device_name, "os": device.os, "last_seen_at": device.last_seen_at},
            )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "users": [
            {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "email_verified": user.email_verified,
                "status": user.status,
                "locale": user.locale,
                "created_at": user.created_at,
                "last_login_at": user.last_login_at,
                "subscription": subscriptions.get(user.id),
                "device": devices.get(user.id),
            }
            for user in users
        ],
    }


@router.patch("/users/{user_id}/status")
def update_user_status(
    user_id: str,
    body: UserStatusChange,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    try:
        parsed_id = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(404, {"code": "user_not_found", "message": "Không tìm thấy tài khoản."})
    user = db.get(User, parsed_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(404, {"code": "user_not_found", "message": "Không tìm thấy tài khoản."})
    previous = user.status
    user.status = body.status
    if body.status == "locked":
        now = utcnow()
        for device in db.scalars(select(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None))).all():
            device.revoked_at = now
            device.revoke_reason = "admin"
        for token in db.scalars(
            select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        ).all():
            token.revoked_at = now
    _audit(
        db,
        admin,
        request,
        "user.status_changed",
        "user",
        str(user.id),
        {"from": previous, "to": body.status, "reason": body.reason},
    )
    db.commit()
    return {"id": str(user.id), "status": user.status}


@router.get("/plans")
def list_plans(admin: AdminAccount = Depends(get_ready_admin), db: Session = Depends(get_db)):
    plans = db.scalars(select(Plan).order_by(Plan.sort_order, Plan.name)).all()
    output = []
    for plan in plans:
        prices = db.scalars(select(PlanPrice).where(PlanPrice.plan_id == plan.id).order_by(PlanPrice.billing_period)).all()
        feature_rows = db.execute(
            select(PlanFeature.feature_code, PlanFeature.limit_value, Feature.name)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .where(PlanFeature.plan_id == plan.id)
        ).all()
        output.append(
            {
                "id": str(plan.id),
                "code": plan.code,
                "name": plan.name,
                "description": plan.description,
                "is_active": plan.is_active,
                "sort_order": plan.sort_order,
                "prices": [
                    {
                        "id": str(price.id),
                        "billing_period": price.billing_period,
                        "amount": str(price.amount),
                        "currency": price.currency,
                        "is_active": price.is_active,
                    }
                    for price in prices
                ],
                "features": [
                    {"code": code, "name": name, "limit_value": limit}
                    for code, limit, name in feature_rows
                ],
            }
        )
    return {"plans": output}


@router.patch("/plans/{plan_id}")
def update_plan(
    plan_id: str,
    body: PlanChange,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    plan = db.get(Plan, _parse_uuid(plan_id, "plan_not_found"))
    if plan is None:
        raise HTTPException(404, {"code": "plan_not_found", "message": "Không tìm thấy gói."})
    changes = {}
    for field in ("name", "description", "is_active", "sort_order"):
        value = getattr(body, field)
        if field in body.model_fields_set and value is not None:
            changes[field] = {"from": getattr(plan, field), "to": value}
            setattr(plan, field, value)
    if changes:
        _audit(db, admin, request, "plan.updated", "plan", str(plan.id), changes)
        db.commit()
    return {"id": str(plan.id), "name": plan.name, "is_active": plan.is_active}


@router.patch("/prices/{price_id}")
def update_price(
    price_id: str,
    body: PriceChange,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    price = db.get(PlanPrice, _parse_uuid(price_id, "price_not_found"))
    if price is None:
        raise HTTPException(404, {"code": "price_not_found", "message": "Không tìm thấy mức giá."})
    changes = {}
    for field in ("amount", "is_active"):
        value = getattr(body, field)
        if field in body.model_fields_set and value is not None:
            before = str(getattr(price, field)) if field == "amount" else getattr(price, field)
            changes[field] = {"from": before, "to": str(value) if field == "amount" else value}
            setattr(price, field, value)
    if changes:
        _audit(db, admin, request, "plan_price.updated", "plan_price", str(price.id), changes)
        db.commit()
    return {"id": str(price.id), "amount": str(price.amount), "is_active": price.is_active}


@router.put("/plans/{plan_id}/features")
def update_plan_features(
    plan_id: str,
    body: PlanFeatureChange,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    plan = db.get(Plan, _parse_uuid(plan_id, "plan_not_found"))
    if plan is None:
        raise HTTPException(404, {"code": "plan_not_found", "message": "Không tìm thấy gói."})
    requested = set(body.feature_codes)
    known = set(db.scalars(select(Feature.code).where(Feature.code.in_(requested))).all()) if requested else set()
    if requested != known:
        raise HTTPException(422, {"code": "feature_not_found", "message": "Danh sách có quyền lợi không tồn tại."})
    current_rows = db.scalars(select(PlanFeature).where(PlanFeature.plan_id == plan.id)).all()
    current = {row.feature_code for row in current_rows}
    for row in current_rows:
        if row.feature_code not in requested:
            db.delete(row)
    for code in requested - current:
        db.add(PlanFeature(plan_id=plan.id, feature_code=code))
    if current != requested:
        _audit(
            db,
            admin,
            request,
            "plan.features_updated",
            "plan",
            str(plan.id),
            {"from": sorted(current), "to": sorted(requested)},
        )
        db.commit()
    return {"plan_id": str(plan.id), "feature_codes": sorted(requested)}


@router.get("/features")
def list_features(admin: AdminAccount = Depends(get_ready_admin), db: Session = Depends(get_db)):
    features = db.scalars(select(Feature).order_by(Feature.name)).all()
    return {
        "features": [
            {"code": feature.code, "name": feature.name, "description": feature.description}
            for feature in features
        ]
    }


@router.get("/payments")
def list_payments(
    q: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    query = (
        select(Payment, User, Plan, PlanPrice)
        .join(User, Payment.user_id == User.id)
        .join(PlanPrice, Payment.plan_price_id == PlanPrice.id)
        .join(Plan, PlanPrice.plan_id == Plan.id)
    )
    if q:
        needle = f"%{q.strip()}%"
        query = query.where(or_(Payment.vnp_txn_ref.ilike(needle), User.email.ilike(needle)))
    if status:
        query = query.where(Payment.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(Payment.created_at.desc()).offset(offset).limit(limit)).all()
    return {
        "total": total,
        "payments": [
            {
                "id": str(payment.id),
                "txn_ref": payment.vnp_txn_ref,
                "user_email": user.email,
                "plan": plan.name,
                "billing_period": price.billing_period,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "status": payment.status,
                "vnp_transaction_no": payment.vnp_transaction_no,
                "vnp_response_code": payment.vnp_response_code,
                "ipn_received_at": payment.ipn_received_at,
                "paid_at": payment.paid_at,
                "created_at": payment.created_at,
            }
            for payment, user, plan, price in rows
        ],
    }


@router.get("/templates")
def list_templates(admin: AdminAccount = Depends(get_ready_admin), db: Session = Depends(get_db)):
    templates = db.scalars(select(Template).order_by(Template.name)).all()
    categories = {item.id: item.name for item in db.scalars(select(TemplateCategory)).all()}
    version_counts = dict(
        db.execute(select(TemplateVersion.template_id, func.count(TemplateVersion.id)).group_by(TemplateVersion.template_id)).all()
    )
    return {
        "templates": [
            {
                "id": str(template.id),
                "slug": template.slug,
                "name": template.name,
                "description": template.description,
                "category_id": template.category_id,
                "category": categories.get(template.category_id),
                "output_kind": template.output_kind,
                "is_premium": template.is_premium,
                "status": template.status,
                "sort_order": template.sort_order,
                "versions_count": version_counts.get(template.id, 0),
            }
            for template in templates
        ]
    }


@router.get("/categories")
def list_categories(admin: AdminAccount = Depends(get_ready_admin), db: Session = Depends(get_db)):
    categories = db.scalars(select(TemplateCategory).order_by(TemplateCategory.sort_order, TemplateCategory.name)).all()
    return {
        "categories": [
            {"id": item.id, "code": item.code, "name": item.name, "icon": item.icon, "sort_order": item.sort_order}
            for item in categories
        ]
    }


@router.post("/categories", status_code=201)
def create_category(
    body: CategoryCreate,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    category = TemplateCategory(code=body.code, name=body.name, icon=body.icon, sort_order=body.sort_order)
    db.add(category)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "category_code_exists", "message": "Mã danh mục đã được dùng."})
    _audit(db, admin, request, "template_category.created", "template_category", str(category.id), {"code": category.code})
    db.commit()
    return {"id": category.id, "code": category.code, "name": category.name, "icon": category.icon, "sort_order": category.sort_order}


@router.post("/templates", status_code=201)
def create_template(
    body: TemplateCreate,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    if body.category_id is not None and db.get(TemplateCategory, body.category_id) is None:
        raise HTTPException(404, {"code": "category_not_found", "message": "Không tìm thấy danh mục."})
    template = Template(
        slug=body.slug,
        name=body.name,
        description=body.description,
        category_id=body.category_id,
        output_kind=body.output_kind,
        is_premium=body.is_premium,
        status=body.status,
    )
    db.add(template)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "template_slug_exists", "message": "Slug mẫu đã tồn tại."})
    _audit(db, admin, request, "template.created", "template", str(template.id), {"slug": template.slug})
    db.commit()
    return {"id": str(template.id), "slug": template.slug, "name": template.name, "status": template.status}


@router.patch("/templates/{template_id}")
def update_template(
    template_id: str,
    body: TemplateChange,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    template = db.get(Template, _parse_uuid(template_id, "template_not_found"))
    if template is None:
        raise HTTPException(404, {"code": "template_not_found", "message": "Không tìm thấy mẫu."})
    changes = {}
    for field in ("name", "description", "category_id", "is_premium", "status"):
        value = getattr(body, field)
        if field in body.model_fields_set and (value is not None or field in {"description", "category_id"}):
            if field == "category_id" and value is not None and db.get(TemplateCategory, value) is None:
                raise HTTPException(404, {"code": "category_not_found", "message": "Không tìm thấy danh mục."})
            changes[field] = {"from": getattr(template, field), "to": value}
            setattr(template, field, value)
    if changes:
        _audit(db, admin, request, "template.updated", "template", str(template.id), changes)
        db.commit()
    return {"id": str(template.id), "name": template.name, "is_premium": template.is_premium, "status": template.status}


@router.get("/assets")
def list_assets(admin: AdminAccount = Depends(get_ready_admin), db: Session = Depends(get_db)):
    audio_tracks = db.scalars(select(AudioTrack).order_by(AudioTrack.created_at.desc())).all()
    assets = db.execute(
        select(TemplateAsset, TemplateVersion, Template)
        .join(TemplateVersion, TemplateAsset.template_version_id == TemplateVersion.id)
        .join(Template, TemplateVersion.template_id == Template.id)
        .order_by(Template.name, TemplateVersion.version, TemplateAsset.kind)
    ).all()
    versions = db.execute(
        select(TemplateVersion, Template)
        .join(Template, TemplateVersion.template_id == Template.id)
        .order_by(Template.name, TemplateVersion.created_at.desc())
    ).all()
    return {
        "audio_tracks": [
            {
                "id": str(track.id),
                "title": track.title,
                "artist": track.artist,
                "duration_ms": track.duration_ms,
                "file_url": track.file_url,
                "file_sha256": track.file_sha256,
                "bpm": str(track.bpm) if track.bpm is not None else None,
                "beat_markers": track.beat_markers,
                "license": track.license,
                "license_note": track.license_note,
                "created_at": track.created_at,
            }
            for track in audio_tracks
        ],
        "versions": [
            {
                "id": str(version.id),
                "template_id": str(template.id),
                "template_name": template.name,
                "version": version.version,
                "duration_ms": version.duration_ms,
                "page_count": version.page_count,
                "is_current": version.is_current,
            }
            for version, template in versions
        ],
        "assets": [
            {
                "id": str(asset.id),
                "template_name": template.name,
                "version": version.version,
                "kind": asset.kind,
                "aspect_code": asset.aspect_code,
                "file_url": asset.file_url,
                "file_sha256": asset.file_sha256,
                "byte_size": asset.byte_size,
            }
            for asset, version, template in assets
        ],
    }


@router.post("/audio-tracks", status_code=201)
def create_audio_track(
    body: AudioTrackCreate,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    if body.beat_markers and any(marker < 0 or marker >= body.duration_ms for marker in body.beat_markers):
        raise HTTPException(422, {"code": "invalid_beat_markers", "message": "Beat marker phải nằm trong thời lượng audio."})
    track = AudioTrack(
        title=body.title,
        artist=body.artist,
        duration_ms=body.duration_ms,
        file_url=body.file_url,
        file_sha256=body.file_sha256.lower(),
        bpm=body.bpm,
        beat_markers=body.beat_markers,
        license=body.license,
        license_note=body.license_note,
    )
    db.add(track)
    _audit(db, admin, request, "audio_track.created", "audio_track", str(track.id), {"title": track.title, "license": track.license})
    db.commit()
    return {"id": str(track.id), "title": track.title, "license": track.license}


@router.post("/template-versions", status_code=201)
def create_template_version(
    body: TemplateVersionCreate,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    template = db.get(Template, body.template_id)
    if template is None:
        raise HTTPException(404, {"code": "template_not_found", "message": "Không tìm thấy mẫu."})
    if body.min_media > body.max_media:
        raise HTTPException(422, {"code": "invalid_media_range", "message": "Số media tối thiểu phải nhỏ hơn hoặc bằng tối đa."})
    if body.default_audio_id and db.get(AudioTrack, body.default_audio_id) is None:
        raise HTTPException(404, {"code": "audio_not_found", "message": "Không tìm thấy audio."})
    if body.is_current:
        for previous in db.scalars(select(TemplateVersion).where(TemplateVersion.template_id == template.id)).all():
            previous.is_current = False
    version = TemplateVersion(
        template_id=template.id,
        version=body.version,
        definition=body.definition,
        min_app_version=body.min_app_version,
        default_audio_id=body.default_audio_id,
        duration_ms=body.duration_ms,
        page_count=body.page_count,
        min_media=body.min_media,
        max_media=body.max_media,
        is_current=body.is_current,
        published_at=utcnow() if body.is_current else None,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "template_version_exists", "message": "Phiên bản này đã tồn tại cho mẫu."})
    _audit(db, admin, request, "template_version.created", "template_version", str(version.id), {"template": template.slug, "version": version.version})
    db.commit()
    return {"id": str(version.id), "template_id": str(template.id), "version": version.version, "is_current": version.is_current}


@router.post("/template-assets", status_code=201)
def create_template_asset(
    body: TemplateAssetCreate,
    request: Request,
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    _super_admin(admin)
    if db.get(TemplateVersion, body.template_version_id) is None:
        raise HTTPException(404, {"code": "template_version_not_found", "message": "Không tìm thấy phiên bản mẫu."})
    if body.aspect_code and db.get(AspectRatio, body.aspect_code) is None:
        raise HTTPException(404, {"code": "aspect_not_found", "message": "Tỉ lệ khung hình chưa được khai báo."})
    asset = TemplateAsset(
        template_version_id=body.template_version_id,
        kind=body.kind,
        aspect_code=body.aspect_code,
        file_url=body.file_url,
        file_sha256=body.file_sha256.lower(),
        byte_size=body.byte_size,
    )
    db.add(asset)
    _audit(db, admin, request, "template_asset.created", "template_asset", str(asset.id), {"kind": asset.kind})
    db.commit()
    return {"id": str(asset.id), "kind": asset.kind}


@router.get("/activity")
def list_admin_activity(
    limit: int = Query(50, ge=1, le=100),
    admin: AdminAccount = Depends(get_ready_admin),
    db: Session = Depends(get_db),
):
    logs = db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit)).all()
    return {
        "events": [
            {
                "id": item.id,
                "admin_email": item.admin_email,
                "action": item.action,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "details": item.details,
                "ip_address": item.ip_address,
                "created_at": item.created_at,
            }
            for item in logs
        ]
    }


def _parse_uuid(value: str, error_code: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        raise HTTPException(404, {"code": error_code, "message": "Không tìm thấy dữ liệu."})
