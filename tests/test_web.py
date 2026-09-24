"""Tests for the optional browser mode (skipped when Flask is absent)."""

from __future__ import annotations

import io
import zipfile

import pytest

from fixtures import synthetic_photo

flask = pytest.importorskip("flask", reason="Flask is an optional extra")

from pixelmuse.web import BatchStore, _render_options, create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def upload(name: str = "photo.png"):
    buffer = io.BytesIO()
    synthetic_photo(240, 180).save(buffer, "PNG")
    buffer.seek(0)
    return buffer, name


def test_index_renders_style_picker(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "Oil Painting" in body
    assert "Pencil Sketch" in body
    assert 'name="style"' in body


def test_health_reports_offline(client):
    payload = client.get("/api/health").json
    assert payload["offline"] is True
    assert payload["app"]


def test_styles_endpoint(client):
    families = client.get("/api/styles").json
    assert "Painting" in families
    assert all({"key", "label", "blurb"} <= set(item) for items in families.values() for item in items)


def test_generate_returns_inline_images(client):
    buffer, name = upload()
    response = client.post(
        "/api/generate",
        data={
            "file": (buffer, name),
            "style": ["oil_painting", "pixel_art"],
            "variants": "2",
            "detail": "0.4",
            "strength": "0.8",
            "max_side": "240",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.json
    assert len(payload["images"]) == 4
    assert payload["seconds"] >= 0
    first = payload["images"][0]
    assert first["data_uri"].startswith("data:image/jpeg;base64,")
    assert first["filename"].endswith(".png")
    assert {item["style"] for item in payload["images"]} == {"oil_painting", "pixel_art"}


def test_generate_requires_style_and_file(client):
    buffer, name = upload()
    missing_style = client.post(
        "/api/generate", data={"file": (buffer, name)}, content_type="multipart/form-data"
    )
    assert missing_style.status_code == 400

    no_file = client.post(
        "/api/generate", data={"style": ["noir"], "variants": "1"},
        content_type="multipart/form-data",
    )
    assert no_file.status_code == 400


def test_generate_rejects_a_non_image(client):
    response = client.post(
        "/api/generate",
        data={
            "file": (io.BytesIO(b"this is not an image"), "notes.txt"),
            "style": ["noir"],
            "variants": "1",
            "max_side": "240",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_zip_download_round_trip(client):
    buffer, name = upload()
    payload = client.post(
        "/api/generate",
        data={"file": (buffer, name), "style": ["noir"], "variants": "2", "max_side": "200"},
        content_type="multipart/form-data",
    ).json
    response = client.get(f"/api/batch/{payload['batch_id']}.zip")
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert len(archive.namelist()) == 2


def test_unknown_batch_expires(client):
    assert client.get("/api/batch/nope.zip").status_code == 404


def test_batch_store_is_bounded():
    store = BatchStore(keep=2)
    ids = [store.put([1]) for _ in range(4)]
    assert store.get(ids[0]) is None
    assert store.get(ids[1]) is None
    assert store.get(ids[3]) == [1]


def test_option_parsing_clamps_values():
    options, variants, max_side = _render_options(
        {"detail": "5", "strength": "-2", "variants": "99", "max_side": "10"}
    )
    assert options.detail == 1.0
    assert options.strength == 0.0
    assert variants == 16
    assert max_side == 320
