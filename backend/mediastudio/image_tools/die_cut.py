from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element, SubElement, tostring

import cv2
import numpy as np
import pyclipper
from PIL import Image

from mediastudio.jobs.manager import Job
from mediastudio.storage.assets import Asset


logger = logging.getLogger("mediastudio.die_cut")
CLIPPER_SCALE = 1000


class DieCutError(RuntimeError):
    pass


class DieCutLineService:
    def run(
        self,
        job: Job,
        asset: Asset,
        *,
        offset_mm: float,
        artwork_width_mm: float,
        auto_detect: bool,
        smooth_path: bool,
        complexity: str,
        strokes: list[dict[str, object]],
        output_directory: Path,
    ) -> tuple[Path, int, int, int, int]:
        if not math.isfinite(offset_mm) or not 0 <= offset_mm <= 20:
            raise DieCutError("Khoảng bù phải nằm trong khoảng 0–20 mm.")
        if not math.isfinite(artwork_width_mm) or not 1 <= artwork_width_mm <= 2000:
            raise DieCutError("Chiều rộng in phải nằm trong khoảng 1–2000 mm.")
        if complexity not in {"Đơn giản", "Vừa", "Chi tiết"}:
            raise DieCutError("Mức độ phức tạp chưa được hỗ trợ.")

        job.update(state="processing", progress=5, stage="Đang đọc ảnh và mask", is_indeterminate=False)
        with Image.open(asset.path) as source:
            rgba = np.asarray(source.convert("RGBA")).copy()
        height, width = rgba.shape[:2]
        if width < 2 or height < 2:
            raise DieCutError("Ảnh quá nhỏ để tạo đường bế.")
        rgb = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2BGR)
        alpha = rgba[:, :, 3]

        mask = self._create_mask(
            rgb,
            alpha,
            auto_detect=auto_detect,
            strokes=strokes,
            width=width,
            height=height,
            job=job,
        )
        job.update(progress=54, stage="Đang tìm và làm sạch contour ngoài", is_indeterminate=False)
        mask = self._clean_mask(mask, complexity=complexity, smooth=smooth_path)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        minimum_area = max(8.0, width * height * {"Đơn giản": 0.00015, "Vừa": 0.00004, "Chi tiết": 0.000008}[complexity])
        contours = [contour for contour in contours if cv2.contourArea(contour) >= minimum_area]
        if not contours:
            raise DieCutError("Không tìm thấy chủ thể. Bật tự động nhận diện hoặc tô mask bằng cọ Giữ.")

        epsilon_ratio = {"Đơn giản": 0.006, "Vừa": 0.0025, "Chi tiết": 0.0008}[complexity]
        polygons: list[list[tuple[int, int]]] = []
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            simplified = cv2.approxPolyDP(contour, max(0.2, perimeter * epsilon_ratio), True)
            points = [(int(point[0][0] * CLIPPER_SCALE), int(point[0][1] * CLIPPER_SCALE)) for point in simplified]
            points = pyclipper.CleanPolygon(points, CLIPPER_SCALE * 0.08)
            if len(points) >= 3:
                polygons.append(points)
        if not polygons:
            raise DieCutError("Đường viền chủ thể quá nhỏ hoặc quá phức tạp để tạo đường bế.")

        job.update(progress=72, stage="Đang bù khoảng cách đường cắt", is_indeterminate=False)
        offset_pixels = offset_mm * width / artwork_width_mm
        if offset_pixels > 0:
            offsetter = pyclipper.PyclipperOffset(miter_limit=2.0, arc_tolerance=0.2 * CLIPPER_SCALE)
            offsetter.AddPaths(polygons, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
            offset_paths = offsetter.Execute(offset_pixels * CLIPPER_SCALE)
        else:
            offset_paths = polygons
        if not offset_paths:
            raise DieCutError("Không tạo được đường offset. Hãy giảm khoảng cách hoặc chọn ảnh khác.")

        # Union expanded components so overlapping sticker borders become one cut path.
        union = pyclipper.Pyclipper()
        union.AddPaths(offset_paths, pyclipper.PT_SUBJECT, True)
        cut_paths = union.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
        cut_paths = [path for path in cut_paths if len(path) >= 3]
        if not cut_paths:
            raise DieCutError("Đường bế rỗng sau khi gộp contour.")

        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / f"{job.job_id}_die-cut.svg"
        job.update(progress=88, stage="Đang xuất SVG đường bế", is_indeterminate=False)
        self._write_svg(output_path, cut_paths, width, height, artwork_width_mm)
        size = output_path.stat().st_size
        if size > 20 * 1024 * 1024:
            output_path.unlink(missing_ok=True)
            raise DieCutError("SVG đường bế quá lớn. Hãy chọn mức Đơn giản hoặc giảm độ phức tạp ảnh.")
        return output_path, width, height, size, len(cut_paths)

    @classmethod
    def _create_mask(
        cls,
        bgr: np.ndarray,
        alpha: np.ndarray,
        *,
        auto_detect: bool,
        strokes: list[dict[str, object]],
        width: int,
        height: int,
        job: Job,
    ) -> np.ndarray:
        alpha_coverage = float(np.mean(alpha > 16))
        if alpha_coverage < 0.995:
            mask = (alpha > 16).astype(np.uint8) * 255
            job.update(progress=20, stage="Đang dùng kênh alpha của ảnh", is_indeterminate=False)
        elif auto_detect:
            mask = cls._mask_from_border_color(bgr)
            if mask is not None:
                job.update(progress=20, stage="Đã nhận diện nền liền màu từ mép ảnh", is_indeterminate=False)
            else:
                job.update(progress=20, stage="Đang tách chủ thể bằng GrabCut", is_indeterminate=False)
                mask = cls._grabcut_rectangle(bgr)
        elif strokes:
            job.update(progress=20, stage="Đang tạo mask từ nét đánh dấu", is_indeterminate=False)
            mask = cls._grabcut_rectangle(bgr)
        else:
            raise DieCutError("Bật Tự động nhận diện hoặc tô vùng chủ thể/nền bằng công cụ Hiệu chỉnh mask.")

        if strokes:
            mask = cls._refine_with_strokes(mask, strokes, width=width, height=height)
            job.update(progress=42, stage="Đã áp dụng nét Giữ/Bỏ trên mask", is_indeterminate=False)
        return mask

    @staticmethod
    def _mask_from_border_color(bgr: np.ndarray) -> np.ndarray | None:
        height, width = bgr.shape[:2]
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        border = np.concatenate((lab[0, :, :], lab[-1, :, :], lab[:, 0, :], lab[:, -1, :]), axis=0)
        background = np.median(border, axis=0)
        distance = np.sqrt(np.sum((lab - background) ** 2, axis=2))
        candidates = (distance <= 18.0).astype(np.uint8)
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates, connectivity=8)
        border_labels = np.unique(np.concatenate((labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1])))
        background_mask = np.isin(labels, border_labels[(border_labels > 0) & (border_labels < component_count)])
        background_ratio = float(np.mean(background_mask))
        foreground_ratio = 1.0 - background_ratio
        if background_ratio < 0.025 or foreground_ratio < 0.003:
            return None
        foreground = (~background_mask).astype(np.uint8) * 255
        count, fg_labels, fg_stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
        if count <= 1:
            return None
        areas = fg_stats[1:, cv2.CC_STAT_AREA]
        if areas.size == 0 or int(areas.max()) < width * height * 0.001:
            return None
        return foreground

    @staticmethod
    def _grabcut_rectangle(bgr: np.ndarray) -> np.ndarray:
        height, width = bgr.shape[:2]
        margin_x = max(1, round(width * 0.04))
        margin_y = max(1, round(height * 0.04))
        rect = (margin_x, margin_y, max(2, width - margin_x * 2), max(2, height - margin_y * 2))
        mask = np.zeros((height, width), dtype=np.uint8)
        background_model = np.zeros((1, 65), dtype=np.float64)
        foreground_model = np.zeros((1, 65), dtype=np.float64)
        try:
            cv2.grabCut(bgr, mask, rect, background_model, foreground_model, 4, cv2.GC_INIT_WITH_RECT)
        except cv2.error as error:
            raise DieCutError("Không thể tự tách chủ thể. Hãy tô vùng Giữ và Bỏ rồi thử lại.") from error
        return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

    @staticmethod
    def _refine_with_strokes(mask: np.ndarray, strokes: list[dict[str, object]], *, width: int, height: int) -> np.ndarray:
        result = mask.copy()
        radius = max(3, round(min(width, height) * 0.012))
        for stroke in strokes:
            mode = stroke.get("mode")
            points = stroke.get("points")
            if mode not in {"foreground", "background"} or not isinstance(points, list) or not points:
                continue
            coordinates: list[tuple[int, int]] = []
            for point in points:
                if not isinstance(point, dict):
                    continue
                x = min(width - 1, max(0, round(float(point.get("x", 0.0)) * (width - 1))))
                y = min(height - 1, max(0, round(float(point.get("y", 0.0)) * (height - 1))))
                coordinates.append((x, y))
            if not coordinates:
                continue
            color = 255 if mode == "foreground" else 0
            for point in coordinates:
                cv2.circle(result, point, radius, color, thickness=-1, lineType=cv2.LINE_AA)
            if len(coordinates) > 1:
                cv2.polylines(result, [np.asarray(coordinates, dtype=np.int32)], False, color, thickness=radius * 2, lineType=cv2.LINE_AA)
        return result

    @staticmethod
    def _clean_mask(mask: np.ndarray, *, complexity: str, smooth: bool) -> np.ndarray:
        kernel_size = {"Đơn giản": 7, "Vừa": 5, "Chi tiết": 3}[complexity]
        if not smooth:
            kernel_size = 3
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        cleaned = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        if complexity == "Đơn giản":
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
        if smooth:
            cleaned = cv2.GaussianBlur(cleaned, (3, 3), 0)
        return np.where(cleaned >= 128, 255, 0).astype(np.uint8)

    @staticmethod
    def _write_svg(path: Path, contours: list[list[tuple[int, int]]], width: int, height: int, artwork_width_mm: float) -> None:
        artwork_height_mm = artwork_width_mm * height / width
        svg = Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "width": f"{artwork_width_mm:.3f}mm",
                "height": f"{artwork_height_mm:.3f}mm",
                "viewBox": f"0 0 {width} {height}",
                "version": "1.1",
            },
        )
        group = SubElement(svg, "g", {"id": "CutContour", "data-layer": "cutline"})
        stroke_width = max(1.0, min(4.0, width * 0.002))
        for index, contour in enumerate(contours, start=1):
            commands = []
            for point_index, (x, y) in enumerate(contour):
                px = x / CLIPPER_SCALE
                py = y / CLIPPER_SCALE
                commands.append(("M" if point_index == 0 else "L") + f"{px:.3f},{py:.3f}")
            commands.append("Z")
            SubElement(
                group,
                "path",
                {
                    "id": f"cutline-{index}",
                    "d": " ".join(commands),
                    "fill": "none",
                    "stroke": "#ff2f92",
                    "stroke-width": f"{stroke_width:.2f}",
                    "stroke-linejoin": "round",
                    "stroke-linecap": "round",
                },
            )
        path.write_bytes(tostring(svg, encoding="utf-8", xml_declaration=True))
