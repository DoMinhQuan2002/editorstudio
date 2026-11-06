"""Run a real loopback HTTP upload→job→download smoke test for Vector V2.

Usage from backend/: `python tools/verify_vectorization_v2_api.py <image-path> <output-svg>`
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import uvicorn

from mediastudio.api import create_app


def _http(url: str, *, token: str, method: str = "GET",
          body: bytes | None = None, content_type: str | None = None) -> tuple[int, dict[str, str], bytes]:
    headers = {"X-Media-Studio-Token": token}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=180) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


def _multipart(file_path: Path) -> tuple[bytes, str]:
    boundary = "----MediaStudio" + uuid4().hex
    file_data = file_path.read_bytes()
    filename = file_path.name.replace('"', "")
    content_type = "image/jpeg" if file_path.suffix.casefold() in {".jpg", ".jpeg"} else "image/png"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode("ascii")
    body = head + file_data + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_vectorization_v2_api.py <image-path> <output-svg>")
    image_path, output_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")
    token = uuid4().hex
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workspace = output_path.parent / (output_path.stem + "_api_workspace")
    model_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MediaStudio" / "models"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    app = create_app(token, workspace, model_root / "realesrgan")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, name="mediastudio-v2-api-smoke", daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                status, _, _ = _http(base + "/api/v1/health", token=token)
                if status == 200:
                    break
            except (URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise RuntimeError("local API did not start")

        multipart, content_type = _multipart(image_path)
        status, _, response = _http(base + "/api/v1/assets", token=token,
                                    method="POST", body=multipart,
                                    content_type=content_type)
        if status != 200:
            raise RuntimeError(f"asset upload failed ({status}): {response[:500]!r}")
        asset = json.loads(response)

        body = json.dumps({"asset_id": asset["assetId"], "engine": "auto",
                           "mode": "auto", "text_mode": "outlined",
                           "transparent_background": True}).encode("utf-8")
        status, _, response = _http(base + "/api/v1/vectorize/jobs", token=token,
                                    method="POST", body=body,
                                    content_type="application/json")
        if status != 202:
            raise RuntimeError(f"job submission failed ({status}): {response[:500]!r}")
        job_id = json.loads(response)["jobId"]

        deadline = time.monotonic() + 600
        last_progress = -1
        while time.monotonic() < deadline:
            status, _, response = _http(base + f"/api/v1/jobs/{job_id}", token=token)
            if status != 200:
                raise RuntimeError(f"job poll failed ({status}): {response[:500]!r}")
            job = json.loads(response)
            if job["progress"] != last_progress:
                print(f"{job['progress']}% {job['stage']}", flush=True)
                last_progress = job["progress"]
            if job["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.25)
        else:
            raise TimeoutError("vector job exceeded 10 minutes")
        if job["state"] != "succeeded":
            raise RuntimeError(job.get("error") or "vector job failed")

        status, headers, svg = _http(base + f"/api/v1/jobs/{job_id}/result", token=token)
        response_content_type = next((value for key, value in headers.items()
                                      if key.casefold() == "content-type"), "")
        if status != 200 or "image/svg+xml" not in response_content_type.casefold():
            raise RuntimeError(f"result download failed ({status}, {response_content_type!r}, {headers!r})")
        if b"<svg" not in svg or b"<image" in svg:
            raise RuntimeError("download is not a vector SVG result")
        output_path.write_bytes(svg)
        print(json.dumps({"state": job["state"], "pipeline": job.get("resultPipeline"),
                          "paths": job.get("resultPaths"), "gradients": job.get("resultGradients"),
                          "textLayers": job.get("resultTextLayers"),
                          "textMode": job.get("resultTextMode"),
                          "warnings": job.get("resultWarnings"),
                          "width": job.get("resultWidth"), "height": job.get("resultHeight"),
                          "sizeBytes": len(svg), "output": str(output_path)}, indent=2), flush=True)
        return 0
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        app.state.jobs.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
