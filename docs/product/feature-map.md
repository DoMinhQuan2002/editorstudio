# Bản đồ chức năng

## Workspace desktop

Ứng dụng WPF mở thành cửa sổ desktop. Các workflow gọi backend Python cục bộ; Media Library cho phép dùng lại tài nguyên giữa các nhóm chức năng.

## Nhóm 1: Image Tools (tham khảo BENDESIGN)

### 1. Nâng cấp ảnh (`image-upscale`)

- Chọn ảnh qua hộp thoại Windows hoặc Media Library.
- Chọn mức nâng cấp/chất lượng, xem trước và lưu kết quả.
- Phân biệt hệ số AI với kích thước resize cuối.

### 2. Chuyển ảnh sang vector (`image-to-vector`)

- Nhập ảnh raster.
- Tạo vector SVG có thể dùng trong thiết kế/in ấn.
- PDF có thể bổ sung thành bước export riêng.

### 3. Tạo đường line bế (`die-cut-line`)

- Nhập artwork và tạo đường bao ngoài.
- Cho phép chỉnh mask/đường viền và khoảng bù đường cắt.
- Xem trước rồi xuất đường bế.

## Nhóm 2: Video Creator

Luồng template-first gồm gallery mẫu, chi tiết mẫu, chọn media tương thích cho từng vị trí, xử lý, xem trước và xuất video. Timeline và composition là cấu trúc nội bộ của renderer; người dùng thao tác theo các bước của mẫu, không dùng giao diện NLE thủ công. Một số lớp overlay có thể dùng tách nền AI để giữ chủ thể khỏi nền. Xem [architecture baseline](../video_creator/VIDEO_CREATOR_ARCHITECTURE_BASELINE.md), [release gates](../video_creator/VIDEO_CREATOR_RELEASE_GATES.md) và [bảng model](../MODELS_AND_FEATURES.md).

## Nhóm 3: Media Library

Quản lý media nguồn, preview, kết quả và metadata; WPF dùng hộp thoại Windows để mở/chọn file và backend giữ bản làm việc cục bộ.

## Nhóm 4: Fashion Studio

Chỉnh sửa ảnh bằng model Qwen-Image-Edit chạy trên máy: thử trang phục, thay bối cảnh và chỉnh màu trang phục. Cần tải model lớn riêng; chi tiết model, giấy phép và cách chuẩn bị nằm trong [bảng chức năng và model](../MODELS_AND_FEATURES.md).
