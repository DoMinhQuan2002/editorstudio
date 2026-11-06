# Media Studio Account API

Server tài khoản, gói và thanh toán (FastAPI + PostgreSQL). Tách riêng với backend xử lý media đang chạy trên máy người dùng.

## Chạy thử trên máy (SQLite, không cần PostgreSQL)

```powershell
cd server\account_api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # rồi sửa .env, xem bên dưới
# Trong .env, để chạy thử nhanh: DATABASE_URL=sqlite:///./mediastudio_dev.db
python -m app.seed --create
python -m pytest -q
uvicorn app.main:app --reload --host 127.0.0.1 --port 8800
```

Trang quản trị mở tại `http://127.0.0.1:8800/admin`. Nó dùng cùng `DATABASE_URL` như Account API và đọc các bảng tài khoản, gói, thanh toán, template, audio, phiên bản và asset. Chạy lần đầu, tạo một tài khoản admin riêng (không dùng tài khoản khách hàng):

```powershell
python -m app.admin_bootstrap --email admin@mediastudio.local --name "Media Studio Admin"
```

Lệnh chỉ tạo admin khi bảng `admin_accounts` chưa có tài khoản; mật khẩu tạm được sinh một lần trong output và buộc đổi ở lần đăng nhập đầu tiên. Không đưa output đó vào log/chia sẻ. Các thay đổi admin được ghi trong `admin_audit_logs`. Database SQLite hiện có được nâng cấp theo hướng chỉ thêm bảng/cột, giữ nguyên các dòng dữ liệu sẵn có.

Admin chạy cùng origin với API, dùng cookie `HttpOnly`/`SameSite=Strict`, giới hạn thử sai mật khẩu và chỉ nghe trên `127.0.0.1` khi chạy lệnh bên dưới. Khi đưa lên máy chủ thật, cần cấu hình HTTPS, `DATABASE_URL` của database server và reverse proxy chỉ public đường dẫn cần thiết.

Tài liệu API tự sinh: http://localhost:8800/docs

Chưa điền SMTP thì mã OTP được in ra cửa sổ chạy server (tiện để thử).

## Chạy với PostgreSQL

1. Tạo database `mediastudio`, chạy `docs/database/media_studio_database.sql` (phần A).
2. Đặt `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/mediastudio` trong `.env`.
3. `python -m app.seed` (thêm giá gói và danh sách mẫu nếu chưa có).

## Cấu hình `.env`

| Nhóm | Biến | Ghi chú |
|---|---|---|
| Bảo mật | `JWT_SECRET` | Chuỗi ngẫu nhiên dài, giữ bí mật |
| Gmail OTP | `SMTP_USERNAME`, `SMTP_PASSWORD` | Gmail + App Password 16 ký tự, cổng 465 |
| Google | `GOOGLE_CLIENT_IDS` | OAuth client loại "Desktop app" |
| Facebook | `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` | Facebook Login |
| VNPay | `VNPAY_TMN_CODE`, `VNPAY_HASH_SECRET` | Đăng ký sandbox: https://sandbox.vnpayment.vn/devreg/ |

Trên trang quản lý VNPay, đặt **IPN URL** là `https://<tên-miền-server>/billing/vnpay/ipn`. IPN phải là địa chỉ công khai có HTTPS; khi thử ở máy có thể dùng ngrok hoặc Cloudflare Tunnel.

## API chính

| Việc | Endpoint |
|---|---|
| Đăng ký bằng email: gửi OTP | `POST /auth/signup/start` |
| Nhập OTP, kích hoạt và đăng nhập | `POST /auth/signup/verify` |
| Gửi lại OTP | `POST /auth/otp/resend` |
| Đăng nhập mật khẩu | `POST /auth/login` |
| Đăng nhập Google (id_token) / Facebook (access_token) | `POST /auth/google`, `POST /auth/facebook` |
| Làm mới phiên | `POST /auth/refresh` |
| Quên / đặt lại mật khẩu | `POST /auth/password/forgot`, `POST /auth/password/reset` |
| Đăng xuất | `POST /auth/logout` |
| Thông tin tài khoản + gói | `GET /me` |
| Danh sách gói và giá | `GET /billing/plans` |
| Tạo link thanh toán VNPay | `POST /billing/vnpay/create` |
| VNPay gọi về (kích hoạt gói) | `GET /billing/vnpay/ipn` |
| Trang trình duyệt sau khi trả tiền | `GET /billing/vnpay/return` |
| App hỏi trạng thái giao dịch | `GET /billing/payments/{txn_ref}` |
| Kiểm tra trước khi xuất | `POST /exports/check` → 200 hoặc 402 `plan_required` |

## Quy tắc đã cài

- Một tài khoản một máy: đăng nhập ở máy mới thu hồi máy cũ; máy cũ nhận lỗi 401 `signed_in_elsewhere`.
- Mã OTP 6 số, hết hạn sau 5 phút, sai 5 lần thì mất hiệu lực, gửi lại cách nhau 60 giây, chỉ lưu dạng mã hóa.
- Gói chỉ kích hoạt qua IPN có chữ ký hợp lệ và đúng số tiền; mua thêm khi còn hạn thì cộng dồn thời gian.
- Mẫu miễn phí luôn xuất được; mẫu trả phí cần quyền `export_premium_templates` (gói Pro).
