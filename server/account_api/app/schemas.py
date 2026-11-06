import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class DeviceInfo(BaseModel):
    device_key: str = Field(min_length=8, max_length=128)
    device_name: str | None = Field(default=None, max_length=120)
    os: str | None = Field(default=None, max_length=60)
    app_version: str | None = Field(default=None, max_length=20)


class SignupStart(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class SignupVerify(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    device: DeviceInfo


class OtpResend(BaseModel):
    email: EmailStr
    purpose: Literal["signup", "reset_password"]


class PasswordLogin(BaseModel):
    email: EmailStr
    password: str
    device: DeviceInfo


class GoogleLogin(BaseModel):
    id_token: str
    device: DeviceInfo


class FacebookLogin(BaseModel):
    access_token: str
    device: DeviceInfo


class RefreshRequest(BaseModel):
    refresh_token: str
    device_key: str


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=128)


class Message(BaseModel):
    message: str


class Entitlements(BaseModel):
    plan_code: str
    plan_name: str
    billing_period: str | None = None
    active_until: datetime | None = None
    features: list[str]


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_url: str | None
    email_verified: bool
    providers: list[str]


class Session(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    user: UserOut
    entitlements: Entitlements


class MeOut(BaseModel):
    user: UserOut
    entitlements: Entitlements


class PlanPriceOut(BaseModel):
    id: uuid.UUID
    billing_period: str
    amount: Decimal
    currency: str


class PlanOut(BaseModel):
    code: str
    name: str
    description: str | None
    features: list[str]
    prices: list[PlanPriceOut]


class CreatePayment(BaseModel):
    plan_price_id: uuid.UUID


class PaymentCreated(BaseModel):
    txn_ref: str
    payment_url: str
    amount: Decimal
    currency: str


class PaymentStatus(BaseModel):
    txn_ref: str
    status: str
    amount: Decimal
    paid_at: datetime | None
    entitlements: Entitlements


class ExportCheck(BaseModel):
    template_slug: str


class ExportDecision(BaseModel):
    allowed: bool
    template_slug: str
    is_premium: bool
