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


# ---------------------------------------------------------------------------
# Text-guided mode ("describe a change")
# ---------------------------------------------------------------------------


def test_index_offers_the_describe_mode(client):
    body = client.get("/").data.decode("utf-8")
    assert 'value="describe"' in body
    assert 'name="description"' in body
    assert 'name="tstyle"' in body
    assert 'name="count"' in body


def test_describe_requires_a_description(client):
    response = client.post(
        "/api/describe",
        data={"file": upload(), "description": "   "},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_describe_requires_an_image(client):
    response = client.post(
        "/api/describe",
        data={"description": "add a crown"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_describe_rejects_bad_numbers(client):
    response = client.post(
        "/api/describe",
        data={"file": upload(), "description": "add a crown", "count": "lots"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_describe_clamps_the_count(client, monkeypatch):
    """The form caps at 16; the server must not trust it blindly."""
    from pixelmuse import textguide

    captured = {}

    def fake_batch(settings, source, progress=None):
        captured["count"] = settings.count
        captured["side"] = settings.output_side
        captured["description"] = settings.description
        captured["style_prompt"] = settings.style_prompt
        return [textguide.RenderedImage(
            image=synthetic_photo(48, 48), style_key=settings.style_key,
            style_label=settings.style_label, variant=0, seed=1,
            width=48, height=48, seconds=0.1,
        )], []

    monkeypatch.setattr(textguide, "generate_batch", fake_batch)
    response = client.post(
        "/api/describe",
        data={
            "file": upload(),
            "description": "make this an old princess in a black dress and a crown",
            "tstyle": "oil_realism",
            "count": "999",
            "output_side": "99999",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert captured["count"] == 16
    assert captured["side"] == 1024
    assert "old princess" in captured["description"]
    assert captured["style_prompt"]


def test_describe_returns_images_and_a_zip(client, monkeypatch):
    from pixelmuse import textguide

    def fake_batch(settings, source, progress=None):
        made = [
            textguide.RenderedImage(
                image=synthetic_photo(48, 48), style_key=settings.style_key,
                style_label=settings.style_label, variant=index, seed=index,
                width=48, height=48, seconds=0.1,
            )
            for index in range(3)
        ]
        return made, []

    monkeypatch.setattr(textguide, "generate_batch", fake_batch)
    response = client.post(
        "/api/describe",
        data={"file": upload(), "description": "add a crown", "tstyle": "noir", "count": "3"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["images"]) == 3
    assert payload["warnings"] == []
    assert payload["images"][0]["data_uri"].startswith("data:image/")

    zip_response = client.get(f"/api/batch/{payload['batch_id']}.zip")
    assert zip_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_response.data)) as archive:
        assert len(archive.namelist()) == 3


def test_describe_reports_partial_failures(client, monkeypatch):
    from pixelmuse import textguide

    def fake_batch(settings, source, progress=None):
        return [textguide.RenderedImage(
            image=synthetic_photo(48, 48), style_key=settings.style_key,
            style_label=settings.style_label, variant=0, seed=1,
            width=48, height=48, seconds=0.1,
        )], ["image 2 failed: service busy"]

    monkeypatch.setattr(textguide, "generate_batch", fake_batch)
    response = client.post(
        "/api/describe",
        data={"file": upload(), "description": "add a crown", "tstyle": "noir", "count": "2"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["images"]) == 1
    assert payload["warnings"] == ["image 2 failed: service busy"]


def test_describe_reports_total_failure_as_502(client, monkeypatch):
    from pixelmuse import textguide

    monkeypatch.setattr(
        textguide, "generate_batch",
        lambda settings, source, progress=None: ([], ["image 1 failed: network unavailable"]),
    )
    response = client.post(
        "/api/describe",
        data={"file": upload(), "description": "add a crown", "tstyle": "noir", "count": "1"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 502
    assert b"internet" in response.data


def test_rejected_upload_is_reported(client, monkeypatch):
    from pixelmuse import textguide

    def fake_batch(settings, source, progress=None):
        raise AssertionError("generation should not start for a bad image")

    monkeypatch.setattr(textguide, "generate_batch", fake_batch)
    response = client.post(
        "/api/describe",
        data={"file": (io.BytesIO(b"this is not an image"), "broken.png"),
              "description": "add a crown"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400

