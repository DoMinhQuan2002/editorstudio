from __future__ import annotations

import mimetypes
import json
import hashlib
import os
import re
import struct
import subprocess
import tempfile
import warnings
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError

from mediastudio.video_editor.cutout import CUTOUT_CACHE_TAG
from mediastudio.video_editor.ffmpeg import FFmpegToolchain, FFmpegUnavailableError, media_stream_info
from mediastudio.video_editor.models import MediaMetadata, VideoProject
from mediastudio.video_editor.project_v2 import (
    VideoProjectV2, apply_api_compatibility_projection, migrate_v1_project,
)


MAX_MEDIA_BYTES = 512 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
MEDIA_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class ProjectRevisionConflict(ValueError):
    """Raised when a stale editor snapshot tries to overwrite a newer project."""

    def __init__(self, expected_revision: int, current_revision: int) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__(
            f"Project đã được lưu ở revision {current_revision}; bản đang sửa là revision "
            f"{expected_revision}. Hãy tải lại project trước khi lưu tiếp."
        )


class VideoMediaStore:
    def __init__(self, root: Path, ffmpeg: FFmpegToolchain) -> None:
        self.root = root
        self.media_directory = root / "media"
        self.preview_directory = root / "previews"
        self.cutout_directory = root / "cutouts"
        self.media_directory.mkdir(parents=True, exist_ok=True)
        self.preview_directory.mkdir(parents=True, exist_ok=True)
        self.cutout_directory.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = ffmpeg
        self._lock = RLock()

    async def import_upload(self, upload: UploadFile) -> MediaMetadata:
        original_name = Path((upload.filename or "media").replace("\\", "/")).name[:180] or "media"
        suffix = Path(original_name).suffix.lower()
        if suffix not in IMAGE_SUFFIXES | VIDEO_SUFFIXES | AUDIO_SUFFIXES:
            await upload.close()
            raise ValueError("Chỉ nhận ảnh JPG/PNG/WebP, video MP4/MOV/MKV/WebM/AVI và âm thanh MP3/WAV/M4A/AAC/OGG/FLAC.")
        # Suffixes are an allow-list for supported containers, not the media type
        # resolver. Inspect the actual image or streams so an audio-only MP4 is not
        # routed into the video editor and a video with audio remains a video asset.
        asset_id = uuid4().hex
        destination = self.media_directory / f"{asset_id}{suffix}"
        temporary = self.media_directory / f".{asset_id}.upload"
        preview_path = self.preview_directory / f"{asset_id}.jpg"
        committed = False
        byte_size = 0
        try:
            with temporary.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    byte_size += len(chunk)
                    if byte_size > MAX_MEDIA_BYTES:
                        raise ValueError("Mỗi tệp media không được vượt quá 512 MB.")
                    output.write(chunk)
            if byte_size == 0:
                raise ValueError("Tệp media rỗng.")

            duration_ms = width = height = None
            video_codec = audio_codec = None
            image_format = None
            kind = ""
            try:
                with Image.open(temporary) as image:
                    image_format = image.format
                    if image.width * image.height > 80_000_000:
                        raise ValueError("Ảnh vượt giới hạn 80 megapixel.")
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", Image.DecompressionBombWarning)
                        image.load()
                    oriented = ImageOps.exif_transpose(image)
                    width, height = oriented.size
                    thumbnail = oriented.convert("RGB")
                    thumbnail.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    thumbnail.save(self.preview_directory / f"{asset_id}.jpg", format="JPEG", quality=84)
                kind = "image"
                thumbnail_available = True
                content_type = Image.MIME.get(image_format, "image/jpeg")
            except UnidentifiedImageError:
                info = media_stream_info(self.ffmpeg, temporary)
                if info["has_video"]:
                    kind = "video"
                elif info["has_audio"]:
                    kind = "audio"
                else:
                    raise ValueError("Tệp không có luồng hình ảnh, video hoặc âm thanh hợp lệ.")
                duration_ms = info["duration_ms"]  # type: ignore[assignment]
                width, height = info["width"], info["height"]  # type: ignore[assignment]
                video_codec, audio_codec = info["video_codec"], info["audio_codec"]  # type: ignore[assignment]
                thumbnail_available = False
                if kind == "video" and (self.ffmpeg.ffmpeg or self.ffmpeg.native_engine is not None):
                    if self.ffmpeg.native_engine is not None:
                        try:
                            frame_width, frame_height, pixels = self.ffmpeg.decode_frame_rgba(
                                temporary, 0, 480, 480
                            )
                            Image.frombytes("RGBA", (frame_width, frame_height), pixels).convert("RGB").save(
                                self.preview_directory / f"{asset_id}.jpg", format="JPEG", quality=84
                            )
                            thumbnail_available = (self.preview_directory / f"{asset_id}.jpg").is_file()
                        except (OSError, ValueError):
                            (self.preview_directory / f"{asset_id}.jpg").unlink(missing_ok=True)
                    if not thumbnail_available and self.ffmpeg.ffmpeg:
                        try:
                            subprocess.run(
                                [self.ffmpeg.ffmpeg, "-y", "-ss", "0", "-i", str(temporary), "-frames:v", "1",
                                 "-vf", "scale=480:480:force_original_aspect_ratio=decrease",
                                 str(self.preview_directory / f"{asset_id}.jpg")],
                                capture_output=True, timeout=20, check=True,
                            )
                            thumbnail_available = (self.preview_directory / f"{asset_id}.jpg").is_file()
                        except (OSError, subprocess.SubprocessError):
                            (self.preview_directory / f"{asset_id}.jpg").unlink(missing_ok=True)
                guessed_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
                content_type = guessed_type if guessed_type.startswith(f"{kind}/") else {
                    "video": "video/mp4", "audio": "audio/mpeg"
                }[kind]

            temporary.replace(destination)
            metadata = MediaMetadata(
                asset_id=asset_id, file_name=original_name, kind=kind, content_type=content_type,
                byte_size=byte_size, duration_ms=duration_ms, width=width, height=height,
                video_codec=video_codec, audio_codec=audio_codec, thumbnail_available=thumbnail_available,
            )
            self._write_metadata(metadata)
            committed = True
            return metadata
        except FFmpegUnavailableError:
            raise
        except (OSError, ValueError, ValidationError, Image.DecompressionBombWarning,
                Image.DecompressionBombError) as error:
            raise ValueError(str(error) or "Không đọc được tệp media.") from error
        finally:
            temporary.unlink(missing_ok=True)
            if not committed:
                destination.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
            await upload.close()

    def get_path(self, asset_id: str) -> Path:
        if not MEDIA_ID_PATTERN.fullmatch(asset_id):
            raise KeyError("Không tìm thấy media.")
        metadata = self.get_metadata(asset_id)
        matches = list(self.media_directory.glob(f"{asset_id}.*"))
        path = next((item for item in matches if item.suffix != ".json" and item.is_file()), None)
        if path is None:
            raise KeyError("Không tìm thấy tệp media trên ổ đĩa.")
        return path

    def get_cutout_path(self, asset_id: str) -> Path:
        metadata = self.get_metadata(asset_id)
        if metadata.kind != "image":
            raise KeyError("Chỉ ảnh mới có thể được tách nền.")
        return self.cutout_directory / f"{asset_id}_{CUTOUT_CACHE_TAG}.png"

    def get_metadata(self, asset_id: str) -> MediaMetadata:
        if not MEDIA_ID_PATTERN.fullmatch(asset_id):
            raise KeyError("Không tìm thấy media.")
        metadata_path = self.media_directory / f"{asset_id}.json"
        try:
            return MediaMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise KeyError("Không tìm thấy metadata media.") from error

    def list_metadata(self) -> list[MediaMetadata]:
        with self._lock:
            deleted = self._deleted_library_ids()
        result = []
        for path in self.media_directory.glob("*.json"):
            if path.stem in deleted:
                continue
            try:
                result.append(MediaMetadata.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValidationError):
                continue
        return sorted(result, key=lambda item: item.file_name.casefold())

    def _deleted_library_ids(self) -> set[str]:
        path = self.root / "library-deleted.json"
        return set(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else set()

    def delete_from_library(self, asset_ids: list[str]) -> list[str]:
        """Remove entries atomically; retain source files for saved projects/jobs."""
        if not 1 <= len(asset_ids) <= 500:
            raise ValueError("Chọn từ 1 đến 500 media mỗi lần xóa.")
        ids = list(dict.fromkeys(asset_ids))
        with self._lock:
            for asset_id in ids:
                self.get_metadata(asset_id)
            deleted = self._deleted_library_ids() | set(ids)
            temporary = self.root / f".library-deleted-{uuid4().hex}.tmp"
            try:
                temporary.write_text(json.dumps(sorted(deleted)), encoding="utf-8")
                temporary.replace(self.root / "library-deleted.json")
            finally:
                temporary.unlink(missing_ok=True)
        return ids

    def thumbnail_path(self, asset_id: str) -> Path:
        self.get_metadata(asset_id)
        path = self.preview_directory / f"{asset_id}.jpg"
        if not path.is_file():
            raise KeyError("Media này chưa có thumbnail.")
        return path

    def filmstrip_path(self, asset_id: str, frame_count: int = 24) -> Path:
        metadata = self.get_metadata(asset_id)
        if metadata.kind != "video":
            raise ValueError("Filmstrip chỉ áp dụng cho tệp video.")
        if frame_count < 4 or frame_count > 24:
            raise ValueError("Số khung hình filmstrip phải từ 4 đến 24.")
        path = self.preview_directory / f"{asset_id}_filmstrip_{frame_count}.jpg"
        if path.is_file():
            return path

        source_path = self.get_path(asset_id)
        duration_ms = metadata.duration_ms
        if duration_ms is None or duration_ms <= 0:
            duration_ms = media_stream_info(self.ffmpeg, source_path)["duration_ms"]
        if not isinstance(duration_ms, int) or duration_ms <= 0:
            raise ValueError("Không đọc được thời lượng video để tạo filmstrip.")

        with self._lock:
            if path.is_file():
                return path
            cell_height = 64
            aspect = (metadata.width or 16) / max(1, metadata.height or 9)
            cell_width = max(32, min(192, round(cell_height * aspect)))
            filmstrip = Image.new("RGB", (cell_width * frame_count, cell_height), (30, 31, 35))
            for index in range(frame_count):
                timestamp_ms = min(duration_ms - 1, round((index + 0.5) * duration_ms / frame_count))
                frame_width, frame_height, pixels = self.ffmpeg.decode_frame_rgba(
                    source_path, timestamp_ms, 640, 360
                )
                frame = Image.frombytes("RGBA", (frame_width, frame_height), pixels).convert("RGB")
                frame = ImageOps.fit(frame, (cell_width, cell_height), method=Image.Resampling.LANCZOS)
                filmstrip.paste(frame, (index * cell_width, 0))

            temporary_path = path.with_suffix(".jpg.tmp")
            try:
                filmstrip.save(temporary_path, format="JPEG", quality=92, subsampling=0, optimize=True)
                temporary_path.replace(path)
            finally:
                temporary_path.unlink(missing_ok=True)
        return path

    def waveform_samples(self, asset_id: str, sample_count: int = 480) -> list[float]:
        metadata = self.get_metadata(asset_id)
        if metadata.kind != "audio" or not metadata.audio_codec:
            raise ValueError("Waveform chỉ áp dụng cho media có luồng âm thanh độc lập.")
        sample_count = max(100, min(2000, sample_count))
        cache_path = self.preview_directory / f"{asset_id}_waveform_{sample_count}.json"
        if cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, list) and all(isinstance(item, (int, float)) for item in cached):
                    return [float(item) for item in cached]
            except (OSError, json.JSONDecodeError):
                cache_path.unlink(missing_ok=True)

        if not self.ffmpeg.ffmpeg:
            raise FFmpegUnavailableError("Cần FFmpeg để tạo waveform âm thanh.")
        try:
            process = subprocess.run(
                [self.ffmpeg.ffmpeg, "-v", "error", "-i", str(self.get_path(asset_id)), "-map", "0:a:0",
                 "-vn", "-ac", "1", "-ar", "1000", "-f", "s16le", "pipe:1"],
                capture_output=True, timeout=600, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("Không thể giải mã âm thanh để tạo waveform.") from error
        if process.returncode != 0 or len(process.stdout) < 2:
            raise ValueError("Không thể đọc dữ liệu âm thanh để tạo waveform.")

        frame_count = len(process.stdout) // 2
        peaks: list[float] = []
        for index in range(sample_count):
            start = index * frame_count // sample_count
            end = min(frame_count, max(start + 1, (index + 1) * frame_count // sample_count))
            if start >= frame_count:
                peaks.append(peaks[-1] if peaks else 0.0)
                continue
            peak = 0
            for (value,) in struct.iter_unpack("<h", process.stdout[start * 2:end * 2]):
                peak = max(peak, abs(value))
            peaks.append(round(peak / 32768.0, 4))
        cache_path.write_text(json.dumps(peaks, separators=(",", ":")), encoding="utf-8")
        return peaks

    def frame_jpeg(self, asset_id: str, timestamp_ms: int) -> bytes:
        metadata = self.get_metadata(asset_id)
        if metadata.kind != "video":
            raise ValueError("Chỉ video mới có thể xem trước theo thời gian nguồn.")
        if timestamp_ms < 0:
            raise ValueError("Thời điểm frame phải lớn hơn hoặc bằng 0.")

        source_path = self.get_path(asset_id)
        duration_ms = metadata.duration_ms
        if duration_ms is None or duration_ms <= 0:
            duration_ms = media_stream_info(self.ffmpeg, source_path)["duration_ms"]
        if not isinstance(duration_ms, int) or duration_ms <= 0:
            raise ValueError("Không đọc được thời lượng video để xem trước frame.")

        bounded_timestamp = min(timestamp_ms, duration_ms - 1)
        width, height, pixels = self.ffmpeg.decode_frame_rgba(
            source_path, bounded_timestamp, 640, 640
        )
        frame = Image.frombytes("RGBA", (width, height), pixels).convert("RGB")
        output = BytesIO()
        frame.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()

    def _write_metadata(self, metadata: MediaMetadata) -> None:
        destination = self.media_directory / f"{metadata.asset_id}.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(metadata.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
        temporary.replace(destination)


class VideoProjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create(self, project: VideoProject | VideoProjectV2) -> VideoProjectV2:
        if isinstance(project, VideoProject):
            project = migrate_v1_project(project)
        with self._lock:
            path = self._path(project.project_id)
            if path.exists():
                raise FileExistsError("ID dự án đã tồn tại.")
            self._write(project, path)
        return project

    def get(self, project_id: str) -> VideoProjectV2:
        path = self._path(project_id)
        try:
            raw = path.read_bytes()
        except FileNotFoundError as error:
            raise KeyError("Không tìm thấy dự án.") from error
        except OSError as error:
            raise ValueError("Không đọc được tệp dự án.") from error
        try:
            payload = json.loads(raw)
            if "schemaVersion" in payload or "schema_version" in payload:
                return VideoProjectV2.model_validate(payload)
            legacy = VideoProject.model_validate(payload)
            project = migrate_v1_project(legacy)
            source_hash = hashlib.sha256(raw).hexdigest()
            project.extensions["migrationV1"] = {
                "sourceSha256": source_hash,
                "sourceRevision": legacy.revision,
            }
            with self._lock:
                # Do not overwrite a concurrent V2 save after our initial read.
                current = path.read_bytes()
                if current != raw:
                    current_payload = json.loads(current)
                    if "schemaVersion" in current_payload or "schema_version" in current_payload:
                        return VideoProjectV2.model_validate(current_payload)
                    raise ValueError("Dữ liệu project thay đổi trong lúc migration.")
                self._backup_v1(path, raw)
                self._write(project, path)
            return project
        except OSError as error:
            raise ValueError("Migration V1→V2 chưa hoàn tất; project gốc được giữ nguyên và backup được giữ lại.") from error
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise ValueError("Tệp dự án bị hỏng hoặc không hợp lệ.") from error

    def save_payload(self, project_id: str, payload: dict[str, object]) -> VideoProjectV2:
        try:
            project = apply_api_compatibility_projection(payload)
        except (ValidationError, TypeError, ValueError, KeyError) as error:
            raise ValueError(f"Project V2 không hợp lệ: {error}") from error
        return self.save(project_id, project)

    def save(self, project_id: str, project: VideoProjectV2) -> VideoProjectV2:
        if not isinstance(project, VideoProjectV2):
            raise ValueError("Project V2 là bắt buộc; từ chối ghi payload schema cũ.")
        if project.project_id != project_id:
            raise ValueError("projectId trong URL và nội dung không khớp.")
        with self._lock:
            path = self._path(project.project_id)
            if not path.exists():
                raise KeyError("Không tìm thấy dự án.")
            current = self.get(project.project_id)
            if current.schema_version != 2:
                raise ValueError("Không thể downgrade schema project.")
            if project.revision != current.revision:
                raise ProjectRevisionConflict(project.revision, current.revision)
            project.updated_at = datetime.now(timezone.utc)
            project.revision = current.revision + 1
            self._write(project, path)
        return project

    def rollback_migration(self, project_id: str) -> None:
        """Restore exact V1 bytes only while the migrated V2 has not been edited."""
        with self._lock:
            path = self._path(project_id)
            current = self.get(project_id)
            marker = current.extensions.get("migrationV1")
            if not isinstance(marker, dict) or current.revision != marker.get("sourceRevision"):
                raise ValueError("Rollback an toàn chỉ khả dụng trước lần Save đầu tiên sau migration.")
            digest = marker.get("sourceSha256")
            backup = path.with_name(f"{path.stem}.v1.{digest}.bak")
            source = backup.read_bytes()
            if hashlib.sha256(source).hexdigest() != digest:
                raise ValueError("Hash backup V1 không khớp; project hiện tại được giữ nguyên.")
            self._restore_bytes_atomic(source, path)

    def list(self) -> list[VideoProjectV2]:
        result = []
        for path in self.root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if "schemaVersion" in payload or "schema_version" in payload:
                    result.append(VideoProjectV2.model_validate(payload))
                else:
                    # Listing is read-only. Migration occurs only when that project is opened.
                    result.append(migrate_v1_project(VideoProject.model_validate(payload)))
            except (OSError, json.JSONDecodeError, ValidationError, TypeError) as error:
                raise ValueError(f"Project không hợp lệ ({path.name}); dữ liệu được giữ nguyên.") from error
        return sorted(result, key=lambda item: item.updated_at, reverse=True)

    def _path(self, project_id: str) -> Path:
        if not MEDIA_ID_PATTERN.fullmatch(project_id):
            raise KeyError("Mã dự án không hợp lệ.")
        return self.root / f"{project_id}.json"

    @staticmethod
    def _write(project: VideoProjectV2, destination: Path) -> None:
        payload = project.model_dump(mode="json", by_alias=True)
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        handle, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}.", suffix=".v2.tmp",
                                                  dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _backup_v1(destination: Path, source: bytes) -> Path:
        digest = hashlib.sha256(source).hexdigest()
        backup = destination.with_name(f"{destination.stem}.v1.{digest}.bak")
        if backup.exists():
            if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
                raise ValueError("Bản backup V1 tồn tại nhưng hash không khớp.")
            return backup
        # Exclusive create guarantees an earlier backup is never overwritten.
        with backup.open("xb") as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
            backup.unlink(missing_ok=True)
            raise ValueError("Không xác minh được hash backup V1.")
        return backup

    @staticmethod
    def _restore_bytes_atomic(source: bytes, destination: Path) -> None:
        handle, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}.", suffix=".rollback.tmp",
                                                  dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(source)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
