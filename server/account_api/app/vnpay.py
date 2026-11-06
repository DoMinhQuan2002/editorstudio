"""VNPay payment gateway (API version 2.1.0): build the pay URL and verify callbacks.

Standard library only. The signing follows VNPay's official Python sample: parameters are
sorted by name, each value is URL-encoded with quote_plus, joined as k=v&k=v, and signed
with HMAC-SHA512 using the merchant hash secret.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

VN_TZ = timezone(timedelta(hours=7))
SUCCESS = "00"


def _query(params: dict[str, str]) -> str:
    return "&".join(f"{k}={quote_plus(str(v))}" for k, v in sorted(params.items()) if v not in (None, ""))


def sign(params: dict[str, str], hash_secret: str) -> str:
    return hmac.new(hash_secret.encode(), _query(params).encode(), hashlib.sha512).hexdigest()


def build_payment_url(*, pay_url: str, tmn_code: str, hash_secret: str, txn_ref: str, amount_vnd: int,
                      order_info: str, return_url: str, client_ip: str, locale: str = "vn",
                      expire_minutes: int = 15, now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(VN_TZ)
    params = {
        "vnp_Version": "2.1.0",
        "vnp_Command": "pay",
        "vnp_TmnCode": tmn_code,
        "vnp_Amount": str(int(amount_vnd) * 100),       # VNPay wants amount x100
        "vnp_CurrCode": "VND",
        "vnp_TxnRef": txn_ref,
        "vnp_OrderInfo": order_info,
        "vnp_OrderType": "other",
        "vnp_Locale": locale,
        "vnp_ReturnUrl": return_url,
        "vnp_IpAddr": client_ip or "127.0.0.1",
        "vnp_CreateDate": now.strftime("%Y%m%d%H%M%S"),
        "vnp_ExpireDate": (now + timedelta(minutes=expire_minutes)).strftime("%Y%m%d%H%M%S"),
    }
    signature = sign(params, hash_secret)
    return f"{pay_url}?{_query(params)}&vnp_SecureHash={signature}"


def verify_callback(query: dict[str, str], hash_secret: str) -> bool:
    """Checks vnp_SecureHash on the return URL or IPN query."""
    received = query.get("vnp_SecureHash", "")
    params = {k: v for k, v in query.items()
              if k.startswith("vnp_") and k not in ("vnp_SecureHash", "vnp_SecureHashType")}
    return bool(received) and hmac.compare_digest(sign(params, hash_secret), received.lower())


# Responses VNPay expects from the IPN endpoint.
IPN_OK = {"RspCode": "00", "Message": "Confirm Success"}
IPN_ORDER_NOT_FOUND = {"RspCode": "01", "Message": "Order not found"}
IPN_ALREADY_CONFIRMED = {"RspCode": "02", "Message": "Order already confirmed"}
IPN_INVALID_AMOUNT = {"RspCode": "04", "Message": "Invalid amount"}
IPN_INVALID_SIGNATURE = {"RspCode": "97", "Message": "Invalid signature"}
IPN_UNKNOWN_ERROR = {"RspCode": "99", "Message": "Unknown error"}
