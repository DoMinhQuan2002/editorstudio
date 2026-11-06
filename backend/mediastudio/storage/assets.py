from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_INPUT_PIXELS = 40_000_000
ACCEPTED_FORMATS = {"JPEG", "PNG", "BMP", "TIFF", "WEBP"}


@dataclass(frozen=True, slots=True)
class Asset:
    asset_id: str
    path: Path
    file_name: str
    width: int
    height: int
    byte_size: int
    mode: str


class AssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.input_directory = root / "inputs"
        self.input_directory.mkdir(parents=True, exist_ok=True)
        self._assets: dict[str, Asset] = {}

    async def import_image(self, upload: UploadFile) -> Asset:
        safe_name = Path(upload.filename or "image").name[:180]
        asset_id = uuid4().hex
        raw_path = self.input_directory / f"{asset_id}.upload"
        normalized_path = self.input_directory / f"{asset_id}.png"
        byte_size = 0

        try:
            with raw_path.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    byte_size += len(chunk)
                    if byte_size > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Tệp vượt quá giới hạn 100 MB.")
                    destination.write(chunk)

            if byte_size == 0:
                raise HTTPException(status_code=400, detail="Tệp ảnh rỗng.")

            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(raw_path) as source:
                    if source.format not in ACCEPTED_FORMATS:
                        raise HTTPException(status_code=415, detail="Định dạng ảnh chưa được hỗ trợ.")
                    if source.width * source.height > MAX_INPUT_PIXELS:
                        raise HTTPException(status_code=413, detail="Ảnh vượt giới hạn 40 megapixel.")
                    source.load()
                    oriented = ImageOps.exif_transpose(source)
                    if oriented.mode not in {"RGB", "RGBA", "L", "LA", "I;16"}:
                        oriented = oriented.convert("RGBA" if "transparency" in source.info else "RGB")
                    oriented.save(
                        normalized_path,
                        format="PNG",
                        icc_profile=source.info.get("icc_profile"),
                    )

            with Image.open(normalized_path) as normalized:
                asset = Asset(
                    asset_id=asset_id,
                    path=normalized_path,
                    file_name=safe_name,
                    width=normalized.width,
                    height=normalized.height,
                    byte_size=byte_size,
                    mode=normalized.mode,
                )
            self._assets[asset_id] = asset
            return asset
        except HTTPException:
            normalized_path.unlink(missing_ok=True)
            raise
        except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError) as error:
            normalized_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Không đọc được tệp ảnh đã chọn.") from error
        finally:
            raw_path.unlink(missing_ok=True)
            await upload.close()

    def get(self, asset_id: str) -> Asset:
        asset = self._assets.get(asset_id)
        if asset is None or not asset.path.is_file():
            raise HTTPException(status_code=404, detail="Không tìm thấy ảnh nguồn. Hãy chọn lại ảnh.")
        return asset
