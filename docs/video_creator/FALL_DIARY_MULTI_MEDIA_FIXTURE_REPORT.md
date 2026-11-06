# FALL DIARY — MULTI-MEDIA FIXTURE REPORT 3.9I

## Kết luận

`FALL_DIARY_MULTI_MEDIA_QA_VERIFIED=false`. Không tìm thấy bộ ảnh thật thứ hai có rights/permission rõ ràng trong workspace. Bộ `task3_9b/second_fixture_set` là synthetic geometry và không thể thay thế ảnh chụp. Bộ private ảnh Fall Diary hiện có được dùng cho local QA trong giới hạn ban đầu, không được coi là fixture set mới hay bộ ảnh được phép phát hành.

## Fixture hiện có

Reference kit mô tả 12 ảnh riêng tư do người dùng cung cấp, local QA only. Task 3.9H dùng 11/12 ảnh; tất cả 11 ảnh được dùng lại trong Task 3.9I chỉ để render bốn profile với mapping cố định. Ảnh nguồn không bị sao chép hoặc sửa trong lần chạy này; SHA-256 trước/sau khớp. Bộ ảnh đều dọc, với kích thước đã ghi trong manifest từ 1151×2048 đến 1536×2048.

| Nhóm cần kiểm thử | Tình trạng bằng chứng hiện có | Kết luận |
|---|---|---|
| Chân dung cận mặt | Có trong bộ private portrait hiện hữu | Có sample local QA, không đại diện tập rộng. |
| Người toàn thân | Có một số ảnh người trong bối cảnh công viên | Có sample local QA. |
| Ảnh phong cảnh/cảnh nền | Có cảnh công viên/cây cối | Có sample local QA; vẫn là ảnh dọc. |
| Ảnh ngang 16:9 hoặc 4:3 | Không có ảnh phù hợp trong fixture đã duyệt | **FIXTURE_MISSING** |
| Ảnh dọc 9:16 | Có; toàn bộ bộ 11 ảnh là ảnh dọc | Có sample local QA. |
| Nhiều người | Có người nhỏ ở hậu cảnh trong một số cảnh công viên; không có bộ group portrait đa dạng | Partial, không đủ làm nhóm test riêng. |
| Không có người | Không có trong bộ ảnh portrait đã dùng; bộ ảnh synthetic không tính | **FIXTURE_MISSING** |
| Nền nhiều chi tiết | Có cảnh ngoài trời/công viên với cây, cỏ và vật thể nền | Có sample local QA. |

Nhóm “cận mặt”, “toàn thân” và “cảnh nền” ở trên chỉ mô tả những gì nhìn thấy trong fixture cục bộ. Không suy diễn thành benchmark đại diện hoặc thông tin nhạy cảm về người trong ảnh.

## Quy tắc quyền sử dụng và bảo vệ dữ liệu

- Chỉ dùng ảnh người dùng trong QA cục bộ, đúng phạm vi được nêu trong reference kit.
- Không thêm ảnh cá nhân vào source control, package phát hành, public artifact hoặc tài liệu công khai.
- MP4/contact sheet của Task 3.9I có thể chứa ảnh cá nhân do được render từ fixture đó; toàn bộ đầu ra nằm trong `artifacts/video_creator/task3_9i` với mục đích local review, không phát hành.
- Không tải thêm ảnh từ Internet hoặc lấy từ thư viện bên ngoài khi chưa có nguồn/giấy phép được phê duyệt.

## Fixture cần bổ sung để đóng gate

Cần người dùng/QA owner cung cấp một bộ ảnh thực khác có quyền dùng rõ ràng, tối thiểu có ảnh ngang 16:9 hoặc 4:3, ảnh không có người, nhóm nhiều người rõ ràng, portrait cận mặt, full-body và nền phức tạp. Cần ghi license/permission và orientation metadata cho từng fixture. Nếu chưa được cấp, giữ `FIXTURE_MISSING` và các gate multi-media/layout ở false; không tạo ảnh tổng hợp rồi gọi là ảnh chụp thực tế.

