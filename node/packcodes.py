"""Pack codes: a QR label for each dispensed pack.

Self-contained: imports nothing from the rest of Isagemi.

    make_code(resident_id, drug, dose, rx_version)  -> PackCode (text + PNG bytes)
    read_code(image)                                -> dict, or None if no QR found
    parse_code_text(text)                           -> dict (for a typed-in code)

The dict that comes back has the same four keys that went in:
    {"resident_id": "R1", "drug": "Warfarin", "dose": "3mg", "rx_version": 2}

Dependencies:
    Making codes and parsing typed-in text need only `segno` (pure Python,
    works on any recent Python).
    Reading codes from an IMAGE also needs `opencv-python-headless`. It is
    imported only when read_code is called, so everything else still works
    if OpenCV is not installed for your Python version.

Errors:
    PackCodeError           text or a QR is not a valid Isagemi pack code,
                            or the fields are invalid. read_code returns None
                            (no error) if the image has no readable QR in it.
    ReaderUnavailableError  read_code was called but OpenCV is not installed.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

import segno

PREFIX = "ISAGEMI1:"  # marks our codes and the format version
FIELDS = ("resident_id", "drug", "dose", "rx_version")

# bytes, a file path, or a numpy image array (a webcam frame)
ImageInput = Union[bytes, bytearray, str, Path, Any]


class PackCodeError(ValueError):
    """The text or QR is not a valid Isagemi pack code."""


class ReaderUnavailableError(RuntimeError):
    """OpenCV is not installed, so images cannot be read."""


@dataclass(frozen=True)
class PackCode:
    text: str  # what is stored inside the QR (also usable as the typed-in code)
    png: bytes  # the QR image as PNG bytes

    def save(self, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.png)
        return path


# ---------- text <-> dict ----------

def encode_text(resident_id: str, drug: str, dose: str, rx_version: int) -> str:
    """Build the text stored in the QR. Validates the inputs."""
    if not str(resident_id).strip():
        raise PackCodeError("resident_id is required")
    if not str(drug).strip():
        raise PackCodeError("drug is required")
    if not str(dose).strip():
        raise PackCodeError("dose is required")
    if isinstance(rx_version, bool) or not isinstance(rx_version, int) or rx_version < 1:
        raise PackCodeError("rx_version must be a whole number, 1 or more")
    body = {
        "resident_id": str(resident_id).strip(),
        "drug": str(drug).strip(),
        "dose": str(dose).strip(),
        "rx_version": rx_version,
    }
    return PREFIX + json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def parse_code_text(text: str) -> dict:
    """Turn code text (from a QR or typed in) back into a dict."""
    text = (text or "").strip()
    if not text.startswith(PREFIX):
        raise PackCodeError("not an Isagemi pack code")
    try:
        data = json.loads(text[len(PREFIX):])
    except json.JSONDecodeError as exc:
        raise PackCodeError("pack code is damaged") from exc
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise PackCodeError("pack code has the wrong fields")
    v = data["rx_version"]
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise PackCodeError("pack code has an invalid rx_version")
    for key in ("resident_id", "drug", "dose"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise PackCodeError(f"pack code has an invalid {key}")
    return {key: data[key] for key in FIELDS}


# ---------- make ----------

def make_code(resident_id: str, drug: str, dose: str, rx_version: int,
              scale: int = 8) -> PackCode:
    """Make the QR label for one pack."""
    text = encode_text(resident_id, drug, dose, rx_version)
    qr = segno.make(text, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=4)
    return PackCode(text=text, png=buf.getvalue())


# ---------- read ----------

def _load_opencv():
    """Import OpenCV and numpy only when reading an image."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ReaderUnavailableError(
            "Reading QR images needs OpenCV. Install it with: "
            "python -m pip install opencv-python-headless  "
            "(or type the code in and use parse_code_text instead)."
        ) from exc
    return cv2, np


def _to_gray_array(image: ImageInput, cv2, np):
    """Accept PNG/JPEG bytes, a file path, or a numpy image (webcam frame)."""
    if isinstance(image, np.ndarray):
        arr = image
    elif isinstance(image, (bytes, bytearray)):
        arr = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    elif isinstance(image, (str, Path)):
        arr = cv2.imread(str(image), cv2.IMREAD_COLOR)
    else:
        raise TypeError("image must be bytes, a path, or a numpy array")
    if arr is None or arr.size == 0:
        raise PackCodeError("could not read the image")
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    return arr


def read_code(image: ImageInput) -> Union[dict, None]:
    """Read a pack code from an image.

    Returns the details dict, or None if no QR code was found.
    Raises PackCodeError if a QR was found but it is not an Isagemi pack code,
    or the image cannot be read. Raises ReaderUnavailableError if OpenCV is
    not installed.
    """
    cv2, np = _load_opencv()
    gray = _to_gray_array(image, cv2, np)
    detector = cv2.QRCodeDetector()
    text, _points, _ = detector.detectAndDecode(gray)
    if not text:
        # Phone photos are often small or soft: try once at double size.
        big = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        text, _points, _ = detector.detectAndDecode(big)
    if not text:
        return None
    return parse_code_text(text)