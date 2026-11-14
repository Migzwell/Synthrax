"""Tests for node/packcodes.py. Run: python -m pytest tests/test_packcodes.py

Needs segno and pytest. Tests that READ images also need
opencv-python-headless; they are skipped (not failed) if it is missing.
"""
import importlib.util
import io

import pytest

from node.packcodes import (
    PackCodeError,
    make_code,
    parse_code_text,
    read_code,
)

MARGARET_V2 = dict(resident_id="R1", drug="Warfarin", dose="3mg", rx_version=2)

HAS_OPENCV = importlib.util.find_spec("cv2") is not None
needs_opencv = pytest.mark.skipif(
    not HAS_OPENCV, reason="opencv-python-headless not installed for this Python"
)

def test_make_code_gives_a_png():
    code = make_code(**MARGARET_V2)
    assert code.png.startswith(b"\x89PNG")
    assert code.text.startswith("ISAGEMI1:")


def test_save_writes_file(tmp_path):
    path = make_code(**MARGARET_V2).save(tmp_path / "labels" / "margaret_v2.png")
    assert path.exists() and path.stat().st_size > 0


def test_typed_in_code_text():
    code = make_code(**MARGARET_V2)
    assert parse_code_text(code.text) == MARGARET_V2
    assert parse_code_text("  " + code.text + "\n") == MARGARET_V2


def test_special_characters_in_text():
    details = dict(resident_id="R2", drug="Co-careldopa", dose="1 tablet (25mg/100mg)", rx_version=1)
    assert parse_code_text(make_code(**details).text) == details


def test_rx_version_comes_back_as_int():
    assert isinstance(parse_code_text(make_code(**MARGARET_V2).text)["rx_version"], int)


def test_same_inputs_give_same_text():
    assert make_code(**MARGARET_V2).text == make_code(**MARGARET_V2).text


def test_newer_pack_has_higher_version():
    """What R3 needs: compare the pack's version with the local record's."""
    v1 = parse_code_text(make_code("R1", "Warfarin", "5mg", 1).text)
    v2 = parse_code_text(make_code("R1", "Warfarin", "3mg", 2).text)
    assert v2["rx_version"] > v1["rx_version"]


@pytest.mark.parametrize("bad", ["", "hello", "ISAGEMI1:", "ISAGEMI1:{not json", 'ISAGEMI1:{"drug":"x"}'])
def test_bad_text_raises(bad):
    with pytest.raises(PackCodeError):
        parse_code_text(bad)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(resident_id="", drug="Warfarin", dose="3mg", rx_version=2),
        dict(resident_id="R1", drug=" ", dose="3mg", rx_version=2),
        dict(resident_id="R1", drug="Warfarin", dose="", rx_version=2),
        dict(resident_id="R1", drug="Warfarin", dose="3mg", rx_version=0),
        dict(resident_id="R1", drug="Warfarin", dose="3mg", rx_version="2"),
        dict(resident_id="R1", drug="Warfarin", dose="3mg", rx_version=True),
    ],
)
def test_make_code_rejects_bad_inputs(kwargs):
    with pytest.raises(PackCodeError):
        make_code(**kwargs)

@needs_opencv
def test_round_trip_png_bytes():
    assert read_code(make_code(**MARGARET_V2).png) == MARGARET_V2


@needs_opencv
def test_round_trip_from_saved_file(tmp_path):
    path = make_code(**MARGARET_V2).save(tmp_path / "margaret_v2.png")
    assert read_code(path) == MARGARET_V2
    assert read_code(str(path)) == MARGARET_V2


@needs_opencv
def test_round_trip_numpy_frame():
    """A webcam frame arrives as a numpy array."""
    import cv2
    import numpy as np

    frame = cv2.imdecode(np.frombuffer(make_code(**MARGARET_V2).png, np.uint8), cv2.IMREAD_COLOR)
    assert read_code(frame) == MARGARET_V2


@needs_opencv
def test_blank_image_returns_none():
    import numpy as np

    assert read_code(np.full((300, 300, 3), 255, dtype=np.uint8)) is None


@needs_opencv
def test_unreadable_bytes_raise():
    with pytest.raises(PackCodeError):
        read_code(b"this is not an image")


@needs_opencv
def test_missing_file_raises(tmp_path):
    with pytest.raises(PackCodeError):
        read_code(tmp_path / "nope.png")


@needs_opencv
def test_qr_that_is_not_ours_raises():
    import segno

    buf = io.BytesIO()
    segno.make("https://example.com").save(buf, kind="png", scale=8, border=4)
    with pytest.raises(PackCodeError):
        read_code(buf.getvalue())

        #opencv doesnt work in this environment so we skip the tests that need it
        #meaning we dont know if barcode reading works thorugh a camera or not