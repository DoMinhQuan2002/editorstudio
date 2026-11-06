from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from mediastudio.video_editor.api import install_video_editor_api


def make_client(root):
    app = FastAPI()
    app.state.token = "test"
    install_video_editor_api(app, root)
    return TestClient(app, headers={"X-Media-Studio-Token": "test"})


def upload(client):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    response = client.post("/api/v1/video/media", files={"file": ("sample.png", buffer.getvalue(), "image/png")})
    assert response.status_code == 201
    return response.json()["assetId"]


def test_bulk_delete_persists_and_keeps_project_sources(tmp_path):
    with make_client(tmp_path) as client:
        ids = [upload(client), upload(client)]
        remaining = upload(client)
        response = client.post("/api/v1/video/media/library-delete", json=ids)
        assert response.status_code == 200
        assert response.json()["deletedAssetIds"] == ids
        assert [item["assetId"] for item in client.get("/api/v1/video/media").json()["media"]] == [remaining]
        for asset_id in ids:
            assert client.get(f"/api/v1/video/media/{asset_id}/content").status_code == 200
            assert client.get(f"/api/v1/video/media/{asset_id}").status_code == 200
        assert client.post("/api/v1/video/media/library-delete", json=ids).status_code == 200
    with make_client(tmp_path) as reopened:
        assert [item["assetId"] for item in reopened.get("/api/v1/video/media").json()["media"]] == [remaining]


@pytest.mark.parametrize("invalid", ["../outside", "f" * 32])
def test_invalid_batch_leaves_every_item_in_library(tmp_path, invalid):
    with make_client(tmp_path) as client:
        asset_id = upload(client)
        assert client.post("/api/v1/video/media/library-delete", json=[asset_id, invalid]).status_code == 404
        assert len(client.get("/api/v1/video/media").json()["media"]) == 1
        assert client.post("/api/v1/video/media/library-delete", json=[]).status_code == 422
        assert client.post("/api/v1/video/media/library-delete", json=[asset_id] * 501).status_code == 422
        assert client.post("/api/v1/video/media/library-delete", json=[asset_id], headers={"X-Media-Studio-Token": "wrong"}).status_code == 401
