from __future__ import annotations

from contextvars import ContextVar


video_request_id: ContextVar[str] = ContextVar("video_request_id", default="-")
