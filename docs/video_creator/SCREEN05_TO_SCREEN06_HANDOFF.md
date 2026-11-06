# Screen 05 → Screen 06 — Handoff Contract

Screen 06 nằm ngoài Task 3.6. Màn 5 không thực hiện full export và không điều hướng đến trang trắng.

## Payload tối thiểu

~~~text
DraftProjectId
DraftRevision
TemplateId
TemplateDefinitionVersion
CompositionReference
SourceFingerprint
~~~

ViewModel dựng payload từ Project V2/revision đang mở và Composition Graph. CompositionReference trỏ đến cùng project đã lưu; fingerprint xác định nguồn media/graph mà preview dựa trên.

## Gate hiện tại

Nút Tiếp theo hiển thị lý do “Màn 6 chưa được triển khai” và vẫn disabled. Khi Screen 06 được xây dựng, chỉ bật sau khi Project V2 hợp lệ, composed preview đã mở và duration được xác minh, không có render/save/validation đang chờ hoặc lỗi chưa xử lý, và mọi chỉnh sửa đã commit vào revision đang hiển thị.

Screen 06 sẽ nhận handoff; việc chỉ đi tiếp không được bắt đầu render MP4.
