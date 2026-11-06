# Video Editor

Feature WPF độc lập dành cho chỉnh sửa video. Project và media vẫn được lưu qua Python backend; preview và export MP4 dùng native video engine C++ khi DLL và FFmpeg CLI khả dụng. Export dựng các cảnh tuần tự, chuyển cảnh cut/fade, lớp chữ, âm thanh clip và track âm thanh thành H.264/AAC. App giữ luồng render Python làm fallback nếu native DLL không tải được.
