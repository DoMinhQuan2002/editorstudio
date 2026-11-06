# Template Definition — schema version 1

Implementation: `backend/mediastudio/video_editor/template_compiler.py` (`TemplateDefinition`). Pydantic `StrictModel` từ chối field lạ. Definition có phiên bản riêng; Project V2 schema không đổi.

## Top-level fields

| Field | Meaning |
|---|---|
| `schemaVersion` | Version của schema definition (`1`). |
| `templateId`, `version`, `name` | ID ổn định và phiên bản SemVer của template. |
| `width`, `height` | Canvas output, số chẵn trong giới hạn Project V2. |
| `frameRateNumerator`, `frameRateDenominator` | FPS rational; phải biểu diễn chính xác trong timebase 90,000. |
| `durationTicks` | Duration timeline bằng 90 kHz ticks. |
| `demoAssetReference`, `posterAssetReference`, `audioAssetReference` | Tham chiếu catalog; không ngụ ý asset được phép phân phối. |
| `slots[]` | Contract media ổn định, tách khỏi timeline. |
| `events[]` | Các khoảng thời gian; event chứa một hoặc nhiều layer. |
| `assetDependencies[]` | Sticker/mask/font/audio/effect và thông tin license cần resolver/preprocessor. Compiler hiện từ chối dependency chưa được giải quyết. |

## Media slots

Mỗi slot có `slotId`, `allowedMediaKinds`, `required`, `reusePolicy` (`allow` hoặc `unique_asset`) và `missingSlotPolicy` (`error` hoặc `skip_event`). Reuse áp dụng giữa slot IDs; một slot có thể được tham chiếu bởi nhiều event. Slot bắt buộc luôn phải báo lỗi nếu thiếu. Với optional slot dùng `skip_event`, compiler bỏ cả event có tham chiếu slot đó, phát warning và không lặp ảnh để bù slot.

## Events và layers

Event giữ `eventId`, `timelineStartTicks`, `durationTicks` và `layers[]`. Một layer có ID riêng, `kind`, `slotId` nếu có media, `layerOrder`, `sourceTimeMapping`, transform/crop-fit/opacity, text/audio style và trường capability như `keyframes`, `maskReference`, `cutoutReference`, `stickerReference`, `transition`.

Một slot không ánh xạ một-một với event. Một event có thể tạo nhiều track/layer. Layer order tăng từ sau ra trước theo Composition Graph. Source mapping hiện chỉ compile được rate 1:1. Timestamps canonical trong Project V2 giữ nguyên ticks; các trường ms bên trong properties chỉ phục vụ compatibility projection.

## Dạng JSON khái quát

```json
{
  "schemaVersion": 1,
  "templateId": "example-template",
  "version": "1.0.0",
  "name": "Example",
  "width": 1080,
  "height": 1920,
  "frameRateNumerator": 30,
  "frameRateDenominator": 1,
  "durationTicks": 900000,
  "demoAssetReference": null,
  "posterAssetReference": null,
  "audioAssetReference": null,
  "slots": [
    {
      "slotId": "hero",
      "allowedMediaKinds": ["image"],
      "required": true,
      "reusePolicy": "allow",
      "missingSlotPolicy": "error"
    }
  ],
  "events": [
    {
      "eventId": "opening",
      "timelineStartTicks": 0,
      "durationTicks": 90000,
      "layers": [
        {
          "layerId": "hero-frame",
          "kind": "image",
          "layerOrder": 0,
          "slotId": "hero",
          "sourceTimeMapping": {
            "sourceStartTicks": 0,
            "rateNumerator": 1,
            "rateDenominator": 1
          },
          "fitMode": "cover",
          "scale": 1.0,
          "opacity": 1.0
        }
      ]
    }
  ],
  "assetDependencies": []
}
```

Đây là ví dụ schema, không phải Fall Diary definition. Definition Fall Diary chưa được tạo vì không có source để xác định duration, event, slot, overlay hoặc asset dependency.
