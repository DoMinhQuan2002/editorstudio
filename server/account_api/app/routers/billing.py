import calendar
import logging
import secrets
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import vnpay
from ..config import get_settings
from ..db import get_db
from ..deps import CurrentUser, client_ip, get_current_user
from ..entitlements import _aware, active_subscription, entitlements_for, plan_features
from ..models import Payment, Plan, PlanPrice, Subscription, User, utcnow
from ..schemas import CreatePayment, PaymentCreated, PaymentStatus, PlanOut, PlanPriceOut

log = logging.getLogger("mediastudio.billing")
router = APIRouter(prefix="/billing", tags=["billing"])

PERIOD_LABEL = {"week": "1 tuần", "month": "1 tháng", "year": "1 năm"}


def add_period(start: datetime, period: str) -> datetime:
    if period == "week":
        return start + timedelta(days=7)
    months = 1 if period == "month" else 12
    month0 = start.month - 1 + months
    year, month = start.year + month0 // 12, month0 % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: DbSession = Depends(get_db)):
    plans = db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))
    out = []
    for plan in plans:
        prices = [PlanPriceOut(id=p.id, billing_period=p.billing_period, amount=p.amount, currency=p.currency)
                  for p in sorted(plan.prices, key=lambda p: ["week", "month", "year"].index(p.billing_period))
                  if p.is_active]
        out.append(PlanOut(code=plan.code, name=plan.name, description=plan.description,
                           features=plan_features(db, plan.id), prices=prices))
    return out


@router.post("/vnpay/create", response_model=PaymentCreated)
def create_vnpay_payment(body: CreatePayment, request: Request, current: CurrentUser = Depends(get_current_user),
                         db: DbSession = Depends(get_db)):
    settings = get_settings()
    if not settings.vnpay_tmn_code or not settings.vnpay_hash_secret:
        raise HTTPException(503, {"code": "payment_not_configured", "message": "Cổng thanh toán VNPay chưa được cấu hình."})
    price = db.get(PlanPrice, body.plan_price_id)
    if price is None or not price.is_active or price.amount <= 0:
        raise HTTPException(404, {"code": "price_not_found", "message": "Gói không tồn tại."})
    plan = db.get(Plan, price.plan_id)

    txn_ref = utcnow().astimezone(vnpay.VN_TZ).strftime("%y%m%d%H%M%S") + secrets.token_hex(3).upper()
    payment = Payment(user_id=current.user.id, plan_price_id=price.id, amount=price.amount, currency=price.currency,
                      status="pending", vnp_txn_ref=txn_ref)
    db.add(payment)
    db.commit()

    url = vnpay.build_payment_url(
        pay_url=settings.vnpay_pay_url, tmn_code=settings.vnpay_tmn_code, hash_secret=settings.vnpay_hash_secret,
        txn_ref=txn_ref, amount_vnd=int(price.amount), return_url=settings.vnpay_return_url,
        order_info=f"Media Studio {plan.name} {PERIOD_LABEL[price.billing_period]} {txn_ref}",
        client_ip=client_ip(request))
    return PaymentCreated(txn_ref=txn_ref, payment_url=url, amount=price.amount, currency=price.currency)


def _activate(db: DbSession, payment: Payment) -> None:
    """Starts a subscription, or extends the active one (buying again adds time)."""
    user = db.get(User, payment.user_id)
    price = db.get(PlanPrice, payment.plan_price_id)
    current = active_subscription(db, user)
    now = utcnow()
    if current is not None and db.get(PlanPrice, current.plan_price_id).plan_id == price.plan_id:
        current.current_period_end = add_period(_aware(current.current_period_end), price.billing_period)
        current.plan_price_id = price.id
        current.renewal_reminded_at = None
        payment.subscription_id = current.id
        return
    if current is not None:            # different plan: the new one replaces it from now
        current.status, current.canceled_at = "canceled", now
        db.flush()
    sub = Subscription(user_id=user.id, plan_price_id=price.id, status="active",
                       current_period_start=now, current_period_end=add_period(now, price.billing_period))
    db.add(sub)
    db.flush()
    payment.subscription_id = sub.id


@router.get("/vnpay/ipn")
def vnpay_ipn(request: Request, db: DbSession = Depends(get_db)):
    """Server-to-server call from VNPay. The only place a plan is activated."""
    query = dict(request.query_params)
    try:
        if not vnpay.verify_callback(query, get_settings().vnpay_hash_secret):
            return vnpay.IPN_INVALID_SIGNATURE
        payment = db.scalar(select(Payment).where(Payment.vnp_txn_ref == query.get("vnp_TxnRef", "")))
        if payment is None:
            return vnpay.IPN_ORDER_NOT_FOUND
        if int(query.get("vnp_Amount", "0")) != int(payment.amount) * 100:
            return vnpay.IPN_INVALID_AMOUNT
        if payment.status != "pending":
            return vnpay.IPN_ALREADY_CONFIRMED

        payment.ipn_received_at = utcnow()
        payment.raw_payload = query
        payment.vnp_transaction_no = query.get("vnp_TransactionNo")
        payment.vnp_response_code = query.get("vnp_ResponseCode")
        payment.vnp_bank_code = query.get("vnp_BankCode")
        payment.vnp_card_type = query.get("vnp_CardType")
        payment.vnp_pay_date = query.get("vnp_PayDate")
        if query.get("vnp_ResponseCode") == vnpay.SUCCESS and query.get("vnp_TransactionStatus") == vnpay.SUCCESS:
            payment.status, payment.paid_at = "succeeded", utcnow()
            _activate(db, payment)
        else:
            payment.status = "canceled" if query.get("vnp_ResponseCode") == "24" else "failed"
        db.commit()
        return vnpay.IPN_OK
    except Exception:  # VNPay retries on errors; log and answer 99
        db.rollback()
        log.exception("VNPay IPN failed for %s", query.get("vnp_TxnRef"))
        return vnpay.IPN_UNKNOWN_ERROR


@router.get("/vnpay/return", response_class=HTMLResponse)
def vnpay_return(request: Request, db: DbSession = Depends(get_db)):
    """Page the browser lands on after paying. Display only; the IPN activates the plan."""
    query = dict(request.query_params)
    valid = vnpay.verify_callback(query, get_settings().vnpay_hash_secret)
    ok = valid and query.get("vnp_ResponseCode") == vnpay.SUCCESS
    title = "Thanh toán thành công" if ok else ("Thanh toán chưa hoàn tất" if valid else "Dữ liệu không hợp lệ")
    note = ("Gói của bạn sẽ được kích hoạt sau vài giây. Hãy quay lại ứng dụng Media Studio."
            if ok else "Bạn có thể đóng trang này và thử lại trong ứng dụng.")
    color = "#22A05A" if ok else "#D23C3C"
    ref = escape(query.get("vnp_TxnRef", ""))
    return f"""<!doctype html><html lang="vi"><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<body style="margin:0;background:#F6F8FD;font-family:Segoe UI,Arial,sans-serif;color:#161A2B;
display:flex;align-items:center;justify-content:center;min-height:100vh">
<div style="background:#fff;border-radius:18px;padding:36px 40px;max-width:440px;text-align:center;
box-shadow:0 10px 40px rgba(27,22,64,.12)">
<div style="width:64px;height:64px;border-radius:32px;background:{color};color:#fff;font-size:34px;
line-height:64px;margin:0 auto 18px">{'✓' if ok else '!'}</div>
<h2 style="margin:0 0 8px">{title}</h2><p style="color:#6E7287;line-height:1.5">{note}</p>
<p style="color:#9AA0B4;font-size:13px">Mã giao dịch: {ref}</p></div></body></html>"""


@router.get("/payments/{txn_ref}", response_model=PaymentStatus)
def payment_status(txn_ref: str, current: CurrentUser = Depends(get_current_user), db: DbSession = Depends(get_db)):
    """The app polls this after opening the VNPay page."""
    payment = db.scalar(select(Payment).where(Payment.vnp_txn_ref == txn_ref, Payment.user_id == current.user.id))
    if payment is None:
        raise HTTPException(404, {"code": "payment_not_found", "message": "Không tìm thấy giao dịch."})
    user = db.get(User, current.user.id)
    return PaymentStatus(txn_ref=txn_ref, status=payment.status, amount=payment.amount, paid_at=payment.paid_at,
                         entitlements=entitlements_for(db, user))
