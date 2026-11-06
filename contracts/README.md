# Backend API contracts

Hợp đồng HTTP/JSON giữa ứng dụng C# WPF và Python backend. FastAPI/Pydantic định nghĩa request/response, media metadata, job progress, kết quả và lỗi; OpenAPI là schema giao tiếp.

File ảnh được WPF stream tới endpoint import; API trả `assetId`. Các request xử lý dùng ID này thay vì đường dẫn filesystem tùy ý. C# API client giữ DTO có kiểu tương ứng và xử lý lỗi API tập trung.

## Vectorization method selection

`POST /api/v1/vectorize/jobs` continues to accept the existing request without `vector_method`; in that case the current `MEDIASTUDIO_VECTORIZE_PIPELINE` dispatch remains in effect. The optional field is independent of `mode` and `text_mode`:

```json
{
  "asset_id": "<asset id>",
  "engine": "auto",
  "mode": "quality",
  "text_mode": "outlined",
  "vector_method": "contour_preserving"
}
```

Allowed methods are `smart_reconstruction` and `contour_preserving`. `smart_reconstruction` explicitly routes to the current production Vectorization V2 implementation. `contour_preserving` is experimental and requires `MEDIASTUDIO_CONTOUR_EXPERIMENTAL=1`; otherwise the API returns HTTP 503 with a structured detail containing `code: CONTOUR_EXPERIMENTAL_DISABLED` and `fallback: false`. It never silently switches methods. Completed jobs expose `resultVectorMethod` and `resultEngineMetadata`; failures expose `errorCode` and `errorDetails`. Contour job metadata marks `wpfPreviewValidated: false` until the desktop preview is manually checked.
