# SPDX-License-Identifier: MIT
"""Raw ADC samples exactly as the radar produced them: the capture card's byte order,
lossless int16 storage and loading of captures.

A capture holds `iq` int16 [frame, chirp, rx, sample, 2] (I, Q) with no window, filter or
scaling applied, and `config`, the .cfg text the radar ran.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def iiqq_to_iq(data: bytes | bytearray, shape: tuple[int, int, int]) -> np.ndarray:
    """Capture-card byte stream -> int16 [chirp, rx, sample, 2] (I, Q).

    Two LVDS lanes carry alternate samples, Q before I, and the card interleaves
    them as Q0 Q1 I0 I1 Q2 Q3 I2 I3 ...
    """
    # [..., sample pair, Q/I, lane] -> [..., sample pair, lane, I/Q]
    iiqq = np.frombuffer(data, dtype="<i2").reshape(*shape[:-1], shape[-1] // 2, 2, 2)
    return iiqq[..., ::-1, :].swapaxes(-1, -2).reshape(*shape, 2)


def iq_to_complex(iq: np.ndarray) -> np.ndarray:
    """int16 [..., sample, 2] (I, Q) -> complex64 [..., sample]; exact, int16 fits in float32."""
    return iq[..., 0].astype(np.float32) + 1j * iq[..., 1].astype(np.float32)


def save_capture(path: Path, iq: np.ndarray, cfg_text: str) -> None:
    """Writes int16 frames [frame, chirp, rx, sample, 2] and the .cfg text to a compressed .npz."""
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, iq=iq, config=cfg_text)


def load_capture(path: Path) -> tuple[np.ndarray, str]:
    """(complex64 frames [frame, chirp, rx, sample], .cfg text) of a capture.

    Also reads older captures, which stored complex64 `frames`.
    """
    with np.load(path) as data:
        frames = iq_to_complex(data["iq"]) if "iq" in data else data["frames"]
        return frames, str(data["config"])
