"""End-to-end tests on a temporary SQLite database.  Run:  python -m pytest -q"""
import os
import tempfile
from urllib.parse import parse_qsl, urlsplit

_db_file = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update(DATABASE_URL=f"sqlite:///{_db_file}", JWT_SECRET="test-secret", SMTP_USERNAME="", SMTP_PASSWORD="",
                  VNPAY_TMN_CODE="TESTTMN1", VNPAY_HASH_SECRET="TESTSECRETKEY", OTP_RESEND_SECONDS="0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

from app import vnpay  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Template  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402
from app.seed import seed  # noqa: E402

SENT: list[tuple[str, str, str]] = []


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        db.add(Template(slug="cut-out-pop", name="Cut Out Pop", output_kind="video", is_premium=True))
        db.commit()
    auth_router.send_otp_email = lambda email, code, purpose, ttl: SENT.append((email, code, purpose))
    with TestClient(app) as c:
        yield c


def device(key):
    return {"device_key": key, "device_name": key, "os": "Windows 11", "app_version": "0.1.0"}


def bearer(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


def signup(client, email, key="machine-1-key"):
    r = client.post("/auth/signup/start", json={"email": email, "password": "secret123", "display_name": "Quan"})
    assert r.status_code == 200, r.text
    code = [c for e, c, p in SENT if e == email and p == "signup"][-1]
    r = client.post("/auth/signup/verify", json={"email": email, "code": "000000" if code != "000000" else "111111",
                                                 "device": device(key)})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "otp_invalid"
    r = client.post("/auth/signup/verify", json={"email": email, "code": code, "device": device(key)})
    assert r.status_code == 200, r.text
    return r.json()


def test_signup_login_and_single_device(client):
    s1 = signup(client, "User.One@Gmail.com")
    assert s1["user"]["email"] == "user.one@gmail.com"
    assert s1["entitlements"]["plan_code"] == "free"
    assert client.get("/me", headers=bearer(s1)).status_code == 200

    # Duplicate sign-up is refused.
    r = client.post("/auth/signup/start", json={"email": "user.one@gmail.com", "password": "secret123"})
    assert r.status_code == 409

    # Wrong password.
    r = client.post("/auth/login", json={"email": "user.one@gmail.com", "password": "nope-nope", "device": device("m2-key-000")})
    assert r.status_code == 401

    # Machine 2 signs in -> machine 1 is signed out.
    s2 = client.post("/auth/login", json={"email": "user.one@gmail.com", "password": "secret123",
                                          "device": device("machine-2-key")}).json()
    r = client.get("/me", headers=bearer(s1))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "signed_in_elsewhere"
    r = client.post("/auth/refresh", json={"refresh_token": s1["refresh_token"], "device_key": "machine-1-key"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "signed_in_elsewhere"
    assert client.get("/me", headers=bearer(s2)).status_code == 200

    # Refresh rotates the token; the old one stops working.
    r = client.post("/auth/refresh", json={"refresh_token": s2["refresh_token"], "device_key": "machine-2-key"})
    assert r.status_code == 200
    r2 = client.post("/auth/refresh", json={"refresh_token": s2["refresh_token"], "device_key": "machine-2-key"})
    assert r2.status_code == 401

    # Machine 1 signs in again -> machine 2 is out.
    s1b = client.post("/auth/login", json={"email": "user.one@gmail.com", "password": "secret123",
                                           "device": device("machine-1-key")}).json()
    assert client.get("/me", headers=bearer(r.json())).status_code == 401
    assert client.get("/me", headers=bearer(s1b)).status_code == 200


def test_password_reset(client):
    signup(client, "reset@gmail.com", key="reset-machine")
    client.post("/auth/password/forgot", json={"email": "reset@gmail.com"})
    code = [c for e, c, p in SENT if e == "reset@gmail.com" and p == "reset_password"][-1]
    r = client.post("/auth/password/reset", json={"email": "reset@gmail.com", "code": code, "new_password": "newsecret1"})
    assert r.status_code == 200
    r = client.post("/auth/login", json={"email": "reset@gmail.com", "password": "newsecret1", "device": device("reset-machine")})
    assert r.status_code == 200


def _ipn(client, payment_url, response_code="00", secret="TESTSECRETKEY", amount=None):
    sent = dict(parse_qsl(urlsplit(payment_url).query))
    query = {"vnp_TmnCode": sent["vnp_TmnCode"], "vnp_Amount": amount or sent["vnp_Amount"],
             "vnp_BankCode": "NCB", "vnp_CardType": "ATM", "vnp_OrderInfo": sent["vnp_OrderInfo"],
             "vnp_PayDate": "20261030150000", "vnp_ResponseCode": response_code, "vnp_TransactionNo": "14000000",
             "vnp_TransactionStatus": response_code, "vnp_TxnRef": sent["vnp_TxnRef"]}
    query["vnp_SecureHash"] = vnpay.sign(query, secret)
    return client.get("/billing/vnpay/ipn", params=query).json()


def test_premium_export_needs_plan_and_vnpay_activates_it(client):
    s = signup(client, "buyer@gmail.com", key="buyer-machine")
    h = bearer(s)

    assert client.post("/exports/check", json={"template_slug": "fall-diary"}, headers=h).json()["allowed"] is True
    r = client.post("/exports/check", json={"template_slug": "cut-out-pop"}, headers=h)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_required"

    plans = client.get("/billing/plans").json()
    pro = next(p for p in plans if p["code"] == "pro")
    month = next(p for p in pro["prices"] if p["billing_period"] == "month")

    created = client.post("/billing/vnpay/create", json={"plan_price_id": month["id"]}, headers=h).json()
    url = created["payment_url"]
    sent = dict(parse_qsl(urlsplit(url).query))
    assert sent["vnp_Amount"] == str(int(float(month["amount"])) * 100)
    assert vnpay.verify_callback(sent, "TESTSECRETKEY")

    assert _ipn(client, url, secret="WRONG")["RspCode"] == "97"
    assert _ipn(client, url, amount="100")["RspCode"] == "04"
    assert _ipn(client, url)["RspCode"] == "00"
    assert _ipn(client, url)["RspCode"] == "02"          # VNPay retry is ignored

    status = client.get(f"/billing/payments/{created['txn_ref']}", headers=h).json()
    assert status["status"] == "succeeded"
    assert status["entitlements"]["plan_code"] == "pro"
    first_end = status["entitlements"]["active_until"]
    assert client.post("/exports/check", json={"template_slug": "cut-out-pop"}, headers=h).json()["allowed"] is True

    # Buying again extends the period.
    again = client.post("/billing/vnpay/create", json={"plan_price_id": month["id"]}, headers=h).json()
    assert _ipn(client, again["payment_url"])["RspCode"] == "00"
    second_end = client.get("/me", headers=h).json()["entitlements"]["active_until"]
    assert second_end > first_end

    # A cancelled payment does not activate anything.
    other = signup(client, "cancel@gmail.com", key="cancel-machine")
    c = client.post("/billing/vnpay/create", json={"plan_price_id": month["id"]}, headers=bearer(other)).json()
    assert _ipn(client, c["payment_url"], response_code="24")["RspCode"] == "00"
    assert client.get(f"/billing/payments/{c['txn_ref']}", headers=bearer(other)).json()["status"] == "canceled"

    page = client.get("/billing/vnpay/return", params={"vnp_TxnRef": "x", "vnp_SecureHash": "bad"})
    assert "không hợp lệ" in page.text
