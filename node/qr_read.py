"""Reads pack-code QR labels from a photo or webcam frame."""
# Photos of a screen or a pack are harder than clean images: several codes at once, small codes,
# blur, glare, a slight angle. So this tries a few detectors on a few cleaned-up versions of the
# image and returns every pack code it finds.
import re

PACK_CODE = re.compile(r"[^|\s]+\|[^|]+\|[^|]+\|[^|]+\|v\d+")


def _versions(img):
    import cv2
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = grey.shape[:2]
    if max(h, w) > 2000:                                  # phone photos: shrink so detection is quick
        f = 2000 / max(h, w)
        grey = cv2.resize(grey, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    yield grey
    yield cv2.resize(grey, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)   # small codes
    yield cv2.adaptiveThreshold(cv2.GaussianBlur(grey, (3, 3), 0), 255,
                                cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5)  # glare, shadows


def _detectors():
    import cv2
    yield cv2.QRCodeDetector()
    if hasattr(cv2, "QRCodeDetectorAruco"):
        yield cv2.QRCodeDetectorAruco()


def read_pack_codes(image_bytes: bytes) -> list[str]:
    """Every distinct pack code (e.g. 'R1|M1|warfarin|3mg|v2') found in the photo, in reading order."""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return []
    found: list[str] = []
    for version in _versions(img):
        for detector in _detectors():
            texts = []
            try:
                ok, multi, _, _ = detector.detectAndDecodeMulti(version)
                if ok:
                    texts += list(multi)
            except cv2.error:
                pass
            try:
                single = detector.detectAndDecode(version)[0]
                texts.append(single)
            except cv2.error:
                pass
            for t in texts:
                t = (t or "").strip()
                if PACK_CODE.fullmatch(t) and t not in found:
                    found.append(t)
        if found:
            break
    return found