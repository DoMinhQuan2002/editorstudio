# Media jobs

Python backend quản lý job cục bộ: tạo, xếp hàng, cập nhật tiến độ, hủy, ghi lỗi hiển thị được và trả kết quả. FastAPI route tạo job rồi trả `jobId`; WPF poll trạng thái qua REST. Worker chạy pipeline ngoài request handler. MVP dùng queue/worker đơn máy, chưa cần Celery/Redis.
