# Project Model V2 schema

## Trạng thái

Schema V2 được triển khai trong `backend/mediastudio/video_editor/project_v2.py`. JSON trao đổi dùng camelCase aliases (`schemaVersion`, `projectId`, `tracks`, `timelineStartTicks`); Python field dùng snake_case. `tracks` là trường bắt buộc. Unknown fields bị từ chối bởi `StrictModel` để tránh silently ghi mất contract chưa biết.

```json
{
  "schemaVersion": 2,
  "projectId": "0123456789abcdef0123456789abcdef",
  "templateId": "free-editor",
  "title": "Untitled",
  "width": 1080,
  "height": 1920,
  "frameRateNumerator": 30000,
  "frameRateDenominator": 1001,
  "timebase": 90000,
  "tracks": [
    {
      "trackId": "11111111111111111111111111111111",
      "kind": "visual",
      "layerOrder": 0,
      "displayName": "Video 1",
      "state": {"visible": true, "locked": false, "muted": false, "solo": false},
      "clips": [
        {
          "clipId": "22222222222222222222222222222222",
          "trackId": "11111111111111111111111111111111",
          "clipKind": "video",
          "timelineStartTicks": 0,
          "sourceStartTicks": 0,
          "durationTicks": 270000,
          "mediaId": "33333333333333333333333333333333",
          "properties": {},
          "templateMetadata": {}
        }
      ]
    }
  ],
  "templateMetadata": {},
  "extensions": {},
  "revision": 1
}
```

`properties` carries the existing type-specific fields (position, scale, transition, audio volume, font/style, fades, etc.) and `templateMetadata` carries template slot/order fields. `mediaId=null` is valid for a template placeholder. Media asset and timeline clip remain separate entities; one media asset may be referenced by multiple clips.

## Identity and ordering

- Project, track and clip IDs are distinct lowercase 32-character hexadecimal IDs.
- A clip has its own ID and a `trackId`; `TimelineTrackV2` validates ownership.
- IDs are retained across move, trim, save and reopen. Split is the operation that creates a new clip identity.
- `layerOrder` is a unique integer persisted on each track; JSON array order is not the source of render ordering.
- The V1 migration creates deterministic UUID5 track IDs from project ID and role/lane. New tracks receive a new ID. Audio clip identity is the prior audio item ID; its persistent lane ID is separate.
- The schema records order; it does not claim unverified CapCut z-order/compositing semantics.

## Time contract

- `timebase = 90000` ticks/second; 1 ms is exactly 90 ticks.
- Frame rate is numerator/denominator. Supported rates must have integral ticks per frame; 30000/1001 fps uses 3003 ticks/frame.
- Timeline and source timestamps are signed 64-bit integer values validated nonnegative. Duration must be positive. Project timeline is limited to 30 minutes; source arithmetic is checked against int64 overflow.
- Clip intervals are half-open `[start, end)`. Same start on distinct tracks is valid. Gaps are valid. Same-track overlap returns `REFERENCE_PENDING` until behavior is confirmed; no implicit ripple or replace occurs.
- Reading/migration does not snap to frames. UI operations may quantize according to existing edit commands. The current renderer only accepts millisecond-aligned times and checks that capability before use.
- Project duration is the maximum end time across clip entities, including audio that extends beyond visuals.

## Track kinds and state

`kind` is `visual`, `text`, or `audio`. Each track persists display name, layer order, visibility/locked/muted/solo state and its clips. Empty tracks remain serializable. Current preview/export capability rejects unsupported state changes instead of ignoring them.

## WPF compatibility projection

The API includes `clips[]`, `textLayers[]`, and `audioTracks[]` for existing WPF editors. These are compatibility views, not canonical storage. Each includes persistent `trackId`/`laneTrackId`, clip identity, and absolute ticks. V2 Save requires all three arrays; missing arrays are rejected. The adapter merges updates into canonical tracks while retaining empty tracks/order and V2 template/extensions. Payload without schema 2 and tracks is rejected.

## Blank and template projects

Free Editor `POST /projects/blank` creates a V2 project with no clip or placeholder; tracks start empty. Template creation also uses `TimelineEngineV2`. Denim Story initializes five 270,000-tick unbound visual placeholders plus its text clip.
