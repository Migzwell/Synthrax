"""QR reading from photos: one code, several codes, blur and angle."""
import io

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
segno = pytest.importorskip("segno")

from node.qr_read import read_pack_codes  # noqa: E402


def label(text, scale=8):
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=4)
    return cv2.imdecode(np.frombuffer(buf.getvalue(), np.uint8), cv2.IMREAD_COLOR)


def jpg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()


def test_one_clean_label():
    assert read_pack_codes(jpg(label("R1|M1|warfarin|3mg|v2"))) == ["R1|M1|warfarin|3mg|v2"]


def test_photographed_at_an_angle_in_dim_light():
    canvas = np.full((1200, 1600, 3), 210, np.uint8)
    qr = label("R1|M1|warfarin|3mg|v2", scale=10)
    canvas[250:250 + qr.shape[0], 450:450 + qr.shape[1]] = qr
    canvas = cv2.warpAffine(canvas, cv2.getRotationMatrix2D((800, 600), 12, 1.0), (1600, 1200),
                            borderValue=(170, 170, 170))
    canvas = (cv2.GaussianBlur(canvas, (5, 5), 0) * np.tile(np.linspace(0.6, 1, 1600), (1200, 1))[..., None])
    assert read_pack_codes(jpg(canvas.astype(np.uint8))) == ["R1|M1|warfarin|3mg|v2"]


def test_several_labels_in_one_photo_are_all_found():
    a, b = label("R1|M1|warfarin|5mg|v1"), label("R2|M4|co-careldopa|1 tablet|v1")
    canvas = np.full((700, 1400, 3), 255, np.uint8)
    canvas[100:100 + a.shape[0], 100:100 + a.shape[1]] = a
    canvas[100:100 + b.shape[0], 800:800 + b.shape[1]] = b
    assert set(read_pack_codes(jpg(canvas))) == {"R1|M1|warfarin|5mg|v1", "R2|M4|co-careldopa|1 tablet|v1"}


def test_other_qr_codes_and_rubbish_are_ignored():
    assert read_pack_codes(jpg(label("https://example.com"))) == []
    assert read_pack_codes(b"not an image") == []