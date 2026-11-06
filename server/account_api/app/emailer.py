import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from .config import get_settings

log = logging.getLogger("mediastudio.email")

_SUBJECTS = {
    "signup": "Mã xác nhận đăng ký Media Studio",
    "login": "Mã đăng nhập Media Studio",
    "reset_password": "Mã đặt lại mật khẩu Media Studio",
    "change_email": "Mã xác nhận đổi email Media Studio",
}


def send_otp_email(to_email: str, code: str, purpose: str, ttl_minutes: int) -> None:
    """Sends the OTP through Gmail SMTP (App Password). Without SMTP settings the code is
    only logged, which is handy for local development."""
    settings = get_settings()
    if (not settings.smtp_username or not settings.smtp_password
            or "DIEN_VAO" in settings.smtp_username or "DIEN_VAO" in settings.smtp_password):
        log.warning("SMTP not configured (SMTP_USERNAME=%r, password set=%s, .env read from %s); OTP for %s (%s): %s",
                    settings.smtp_username, bool(settings.smtp_password), os.getcwd(), to_email, purpose, code)
        return

    msg = EmailMessage()
    msg["Subject"] = _SUBJECTS.get(purpose, "Mã xác nhận Media Studio")
    msg["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email or settings.smtp_username))
    msg["To"] = to_email
    msg.set_content(
        f"Mã xác nhận của bạn là: {code}\n\n"
        f"Mã có hiệu lực trong {ttl_minutes} phút. Không chia sẻ mã này với bất kỳ ai.\n"
        "Nếu bạn không yêu cầu mã này, hãy bỏ qua email.\n\n— Media Studio"
    )
    msg.add_alternative(f"""\
<div style="font-family:Segoe UI,Arial,sans-serif;max-width:480px;margin:auto;color:#161A2B">
  <h2 style="color:#5A4CFA;margin-bottom:4px">Media Studio</h2>
  <p>Mã xác nhận của bạn:</p>
  <p style="font-size:32px;font-weight:700;letter-spacing:8px;background:#F6F8FD;border-radius:12px;
            padding:16px;text-align:center;margin:12px 0">{code}</p>
  <p style="color:#6E7287">Mã có hiệu lực trong {ttl_minutes} phút. Không chia sẻ mã này với bất kỳ ai.<br>
     Nếu bạn không yêu cầu mã này, hãy bỏ qua email.</p>
</div>""", subtype="html")

    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20) as smtp:
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
    else:  # 587 STARTTLS
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls(context=context)
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
