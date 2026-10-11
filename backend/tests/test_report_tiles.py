"""The run report's map tiles (app.api.run_export._tile_picture): a tile server that serves its tiles gzipped
(an mbtiles store does) still gives a stitched picture (11 October 2026: the local satellite and topo tiles came
back as bytes PIL could not read, and every report had no map)."""

from __future__ import annotations

import gzip
import io
import urllib.request

from PIL import Image

from app.api import run_export


class _Response:
    def __init__(self, body: bytes, encoding: str | None):
        self.body, self.headers = body, {"Content-Encoding": encoding} if encoding else {}

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _jpeg(colour=(200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), colour).save(buffer, "JPEG")
    return buffer.getvalue()


def test_a_gzipped_tile_is_stitched_like_a_plain_one(monkeypatch):
    served = {"plain": 0, "gzip": 0}

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        if "/plain/" in url:
            served["plain"] += 1
            return _Response(_jpeg(), None)
        served["gzip"] += 1
        return _Response(gzip.compress(_jpeg()), "gzip")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    x, y = run_export._mercator(31.23, 30.05, 10)
    plain = run_export._tile_picture("http://tiles/plain/{z}/{x}/{y}.jpg", 10, x - 300, y - 200, 600, 400, 300, 200)
    zipped = run_export._tile_picture("http://tiles/gz/{z}/{x}/{y}.jpg", 10, x - 300, y - 200, 600, 400, 300, 200)
    assert plain and zipped and plain.startswith("data:image/jpeg;base64,")
    assert served["plain"] == served["gzip"] == 12
    picture = Image.open(io.BytesIO(__import__("base64").b64decode(zipped.split(",", 1)[1])))
    assert picture.size == (300, 200) and picture.getpixel((10, 10))[0] > 150
