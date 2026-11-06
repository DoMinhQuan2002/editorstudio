"""ORM models for the tables in docs/database/media_studio_database.sql (server part).

Types are kept portable (Uuid, JSON, String) so tests can run on SQLite; in production
create the schema from the SQL file on PostgreSQL. Emails are stored lower-case.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        Numeric, SmallInteger, String, Text, UniqueConstraint, Uuid, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(10), default="vi")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    identities: Mapped[list["UserIdentity"]] = relationship(back_populates="user")


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"), UniqueConstraint("user_id", "provider"))
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))          # email | google | facebook
    provider_user_id: Mapped[str] = mapped_column(String(255))
    provider_email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="identities")


class EmailOtp(Base):
    __tablename__ = "email_otps"
    __table_args__ = (Index("ix_email_otps_lookup", "email", "purpose", "created_at"),)
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(20))           # signup | login | reset_password | change_email
    code_hash: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_key"),
        # One account = one machine: at most one non-revoked device per user.
        Index("ux_devices_one_active", "user_id", unique=True,
              postgresql_where=text("revoked_at IS NULL"), sqlite_where=text("revoked_at IS NULL")),
    )
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    device_key: Mapped[str] = mapped_column(String(128))
    device_name: Mapped[str | None] = mapped_column(String(120))
    os: Mapped[str | None] = mapped_column(String(60))
    app_version: Mapped[str | None] = mapped_column(String(20))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(30))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("refresh_tokens.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    prices: Mapped[list["PlanPrice"]] = relationship(back_populates="plan")


class PlanPrice(Base):
    __tablename__ = "plan_prices"
    __table_args__ = (CheckConstraint("billing_period IN ('week','month','year')"),)
    id: Mapped[uuid.UUID] = _id()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    billing_period: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    plan: Mapped[Plan] = relationship(back_populates="prices")


class Feature(Base):
    __tablename__ = "features"
    code: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)


class PlanFeature(Base):
    __tablename__ = "plan_features"
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    feature_code: Mapped[str] = mapped_column(ForeignKey("features.code"), primary_key=True)
    limit_value: Mapped[int | None] = mapped_column(Integer)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ux_subscriptions_one_live", "user_id", unique=True,
              postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    plan_price_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plan_prices.id"))
    status: Mapped[str] = mapped_column(String(20))            # pending | active | expired | canceled
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renewal_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    plan_price: Mapped[PlanPrice] = relationship()


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id"))
    plan_price_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plan_prices.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    vnp_txn_ref: Mapped[str] = mapped_column(String(100), unique=True)
    vnp_transaction_no: Mapped[str | None] = mapped_column(String(50))
    vnp_response_code: Mapped[str | None] = mapped_column(String(5))
    vnp_bank_code: Mapped[str | None] = mapped_column(String(20))
    vnp_card_type: Mapped[str | None] = mapped_column(String(20))
    vnp_pay_date: Mapped[str | None] = mapped_column(String(14))
    ipn_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    plan_price: Mapped[PlanPrice] = relationship()


class TemplateCategory(Base):
    __tablename__ = "template_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    icon: Mapped[str | None] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class AspectRatio(Base):
    __tablename__ = "aspect_ratios"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)


class AudioTrack(Base):
    __tablename__ = "audio_tracks"

    id: Mapped[uuid.UUID] = _id()
    title: Mapped[str] = mapped_column(String(160))
    artist: Mapped[str | None] = mapped_column(String(160))
    duration_ms: Mapped[int] = mapped_column(Integer)
    file_url: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    bpm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    beat_markers: Mapped[list | None] = mapped_column(JSON)
    license: Mapped[str] = mapped_column(String(40))
    license_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Template(Base):
    """Only the columns the account server needs (export gate)."""
    __tablename__ = "templates"
    id: Mapped[uuid.UUID] = _id()
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("template_categories.id", ondelete="SET NULL"))
    output_kind: Mapped[str] = mapped_column(String(10))       # video | image
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="published")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version"),)

    id: Mapped[uuid.UUID] = _id()
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(40))
    definition: Mapped[dict] = mapped_column(JSON)
    min_app_version: Mapped[str | None] = mapped_column(String(20))
    default_audio_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audio_tracks.id", ondelete="SET NULL"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    min_media: Mapped[int] = mapped_column(Integer, default=1)
    max_media: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TemplateVersionAspect(Base):
    __tablename__ = "template_version_aspects"

    template_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("template_versions.id", ondelete="CASCADE"), primary_key=True
    )
    aspect_code: Mapped[str] = mapped_column(ForeignKey("aspect_ratios.code"), primary_key=True)
    canvas_width: Mapped[int] = mapped_column(Integer)
    canvas_height: Mapped[int] = mapped_column(Integer)
    layout_override: Mapped[dict | None] = mapped_column(JSON)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class TemplateAsset(Base):
    __tablename__ = "template_assets"

    id: Mapped[uuid.UUID] = _id()
    template_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("template_versions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    aspect_code: Mapped[str | None] = mapped_column(ForeignKey("aspect_ratios.code"))
    file_url: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(BigInteger)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_events_user_day", "user_id", "event", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    event: Mapped[str] = mapped_column(String(40))
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("templates.id"))
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminAccount(Base):
    """Separate operator credentials; customer accounts never gain admin access."""
    __tablename__ = "admin_accounts"

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Media Studio Admin")
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default="super_admin")
    status: Mapped[str] = mapped_column(String(20), default="active")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (Index("ix_admin_audit_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_accounts.id", ondelete="SET NULL"))
    admin_email: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
