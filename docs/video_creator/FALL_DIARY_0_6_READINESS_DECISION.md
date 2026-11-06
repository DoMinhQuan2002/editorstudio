# FALL DIARY — DEFINITION 0.6 READINESS DECISION

## Quyết định

**Không tạo Definition 0.6 trong Task 3.9I.** Giữ `0.5.0-layer-structure-pilot` làm baseline pilot và lưu Reference Layout / Editorial Safe như QA variants. Không thay default policy, không thêm UI option, không nâng gate `READY_FOR_USERS`.

Đây là quyết định hoãn có căn cứ, không phải kết luận 0.5 đã đạt chất lượng phát hành. `FALL_DIARY_0_6_DECISION_READY=true` nghĩa là đã chọn rõ không tạo version mới khi thiếu bằng chứng; không có nghĩa Definition 0.6 đã được phê duyệt.

## Lý do chưa đủ điều kiện thay đổi

1. Bộ fixture thật thứ hai có quyền dùng chưa có; toàn bộ 11 ảnh private hiện có là portrait. Ảnh ngang và ảnh không có người còn `FIXTURE_MISSING`.
2. Không có annotation face/subject nên không thể định lượng title/card occlusion; không có detector đã kiểm chứng.
3. Muse là screen recording, không có source project/keyframes. Các timestamp candidate và motion source còn chưa xác định.
4. Candidate 13.267s vẫn là background cut hay foreground insert chưa rõ; title end-time sau 13.833s bị che. Không sửa hai giả định này bằng cách tạo version mới.
5. Chưa có soundtrack/timing được cấp quyền, cutout hoặc evidence để tuyên bố reference fidelity.
6. Preview/Export parity của hai layout QA đạt trên shared renderer, nhưng GUI Save/Reopen/Export cho variant mới chưa chạy.

## Điều kiện xem xét 0.6 sau này

- Có fixture thực được phê duyệt, gồm ngang/dọc, cận mặt, full-body, nhiều người, không người và nền chi tiết.
- Có protocol annotation rõ ràng; báo tỷ lệ giao mặt/chủ thể/text/card theo frame và không đưa annotation fixture vào production logic.
- Người dùng review hai layout và chọn thay đổi cụ thể.
- Có bằng chứng mới về event 13.267s/title end nếu định sửa timeline; nếu chưa, tiếp tục bảo lưu uncertainty.
- Mọi thay đổi dùng shared Template Compiler/Project V2/Composition Graph, giữ 11-slot contract trừ khi có lý do được duyệt, giữ Definition cũ và chạy regression/GUI acceptance.

