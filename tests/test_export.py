"""Tests for the export helpers (zip, pdf, batch saving)."""

from __future__ import annotations

import io
import zipfile

from fixtures import synthetic_photo
from pixelmuse import export
from pixelmuse.generator import render_many


def _batch(source):
    return render_many(source, ["oil_painting", "charcoal"], variants=2, max_side=140, seed=42)


def test_save_batch_writes_every_image(tmp_path):
    source = synthetic_photo()
    batch = _batch(source)
    written = export.save_batch(batch, tmp_path / "out", format_ext=".png")
    assert len(written) == len(batch) == 4
    for path in written:
        assert path.exists() and path.stat().st_size > 0


def test_save_batch_does_not_overwrite_on_repeat(tmp_path):
    source = synthetic_photo()
    out = tmp_path / "out"
    first = export.save_batch(_batch(source), out)
    second = export.save_batch(_batch(source), out)
    assert set(first).isdisjoint(second)
    assert len(list(out.glob("*.png"))) == 8


def test_zip_contains_named_entries():
    batch = _batch(synthetic_photo())
    payload = export.batch_to_zip_bytes(batch, format_ext=".png")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert len(names) == 4
        assert all(name.endswith(".png") for name in names)
        for name in names:
            assert archive.read(name)


def test_pdf_is_a_valid_pdf():
    batch = _batch(synthetic_photo())
    payload = export.batch_to_pdf_bytes(batch)
    assert payload.startswith(b"%PDF")
    assert len(payload) > 1000


def test_contact_sheet_bytes():
    batch = _batch(synthetic_photo())
    payload = export.contact_sheet_bytes(batch, columns=2)
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"


def test_metadata_lines():
    batch = _batch(synthetic_photo())
    lines = export.metadata_lines(batch)
    assert len(lines) == 4
    assert all("seed=" in line for line in lines)
