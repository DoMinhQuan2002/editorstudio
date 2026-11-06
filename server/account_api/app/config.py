from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./mediastudio_dev.db"
    jwt_secret: str = "dev-only-secret-change-me"
    access_token_minutes: int = 30
    refresh_token_days: int = 60
    public_base_url: str = "http://localhost:8800"

    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 60

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Media Studio"

    google_client_ids: str = ""          # comma separated
    facebook_app_id: str = ""
    facebook_app_secret: str = ""

    vnpay_tmn_code: str = ""
    vnpay_hash_secret: str = ""
    vnpay_pay_url: str = "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
    vnpay_return_url: str = "http://localhost:8800/billing/vnpay/return"

    @property
    def google_client_id_list(self) -> list[str]:
        return [c.strip() for c in self.google_client_ids.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
