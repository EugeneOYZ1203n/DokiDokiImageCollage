"""Saliency map: spectral residual on Lab channels, centre prior, optional face boost."""
from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image

_SAL_SIDE = 128
_face_cascade = None
_face_tried = False


def _faces(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    global _face_cascade, _face_tried
    if not _face_tried:
        _face_tried = True
        try:
            path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            if os.path.exists(path):  # not shipped with every OpenCV build
                c = cv2.CascadeClassifier(path)
                _face_cascade = None if c.empty() else c
        except Exception:
            _face_cascade = None
    if _face_cascade is None:
        return []
    try:
        return [tuple(int(v) for v in f) for f in _face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(20, 20))]
    except Exception:
        return []


def saliency_map(img: Image.Image, faces: bool = True) -> np.ndarray:
    """Float32 map in [0, 1], same aspect as `img`, long side <= 128."""
    im = img.convert("RGB")
    w, h = im.size
    s = _SAL_SIDE / max(w, h)
    sw, sh = max(2, round(w * s)), max(2, round(h * s))
    small = im.resize((sw, sh), Image.BILINEAR)
    arr = np.asarray(small)
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.float32)

    sal = np.zeros((sh, sw), np.float32)
    for c in range(3):
        f = np.fft.fft2(lab[:, :, c])
        log_amp = np.log(np.abs(f) + 1e-8)
        phase = np.angle(f)
        resid = log_amp - cv2.blur(log_amp.astype(np.float32), (3, 3))
        ch = np.abs(np.fft.ifft2(np.exp(resid + 1j * phase))) ** 2
        sal += ch.astype(np.float32)
    sal = cv2.GaussianBlur(sal, (0, 0), sigmaX=max(sw, sh) * 0.03)
    sal -= sal.min()
    if sal.max() > 0:
        sal /= sal.max()

    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    gauss = np.exp(-(((xx - sw / 2) / (sw * 0.5)) ** 2 + ((yy - sh / 2) / (sh * 0.5)) ** 2))
    sal = sal * (0.6 + 0.4 * gauss)

    if faces:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        for fx, fy, fw, fh in _faces(gray):
            cx, cy = fx + fw / 2, fy + fh / 2
            blob = np.exp(-(((xx - cx) / (fw * 0.8)) ** 2 + ((yy - cy) / (fh * 0.8)) ** 2))
            sal = np.maximum(sal, blob.astype(np.float32))

    if sal.max() > 0:
        sal /= sal.max()
    return sal
