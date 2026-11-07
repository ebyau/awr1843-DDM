# SPDX-License-Identifier: MIT
"""Raw ADC samples exactly as the radar produced them: the capture card's byte order,
lossless int16 storage, loading of captures, and their plain (unwindowed) spectrum.

A capture (.npz, format 2) holds:
  iq         int16 [frame, chirp, rx, sample, 2] (I, Q), no window, filter or scaling applied
  config     the .cfg text the radar ran
  complete   bool [frame]; False where the capture card lost data: the frame's contents are
             unreliable (partly zero-filled). No frame is left out after the first one received,
             so frame k started k frame periods after frame 0 (format 2 only).
  timestamp  float64 [frame]; PC clock (Unix s) when the host read the frame's first data;
             approximate, and only roughly spaced for incomplete frames
  meta       JSON: format, mode ("ddm" or "tdm"), frames, incomplete, start_time, host version
             and git commit
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import numpy as np

from .cfg import mode, parse_cfg

FORMAT = 2


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


@dataclass(frozen=True)
class Capture:
    """A loaded capture; see the module docstring for the fields."""

    iq: np.ndarray
    config: str
    complete: np.ndarray
    timestamp: np.ndarray
    meta: dict = field(default_factory=dict)

    @property
    def frames(self) -> np.ndarray:
        """complex64 [frame, chirp, rx, sample]."""
        return iq_to_complex(self.iq)


def save_capture(path: Path, iq: np.ndarray, cfg_text: str, complete: np.ndarray | None = None,
                 timestamp: np.ndarray | None = None) -> None:
    """Writes int16 frames [frame, chirp, rx, sample, 2], the .cfg text and per-frame metadata
    to a compressed .npz. Missing complete/timestamp mean all complete, times unknown (NaN)."""
    count = len(iq)
    complete = np.ones(count, bool) if complete is None else np.asarray(complete, bool)
    timestamp = np.full(count, np.nan) if timestamp is None else np.asarray(timestamp, np.float64)
    if complete.shape != (count,) or timestamp.shape != (count,):
        raise ValueError(f"complete and timestamp need one entry per frame ({count})")
    start = timestamp[0] if count and math.isfinite(timestamp[0]) else None
    meta = {
        "format": FORMAT,
        "mode": mode(parse_cfg(cfg_text)),
        "frames": count,
        "incomplete": int(count - complete.sum()),
        "start_time": datetime.fromtimestamp(start, UTC).isoformat() if start is not None else None,
        "host": host_version(),
        "commit": git_commit(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, iq=iq, config=cfg_text, complete=complete, timestamp=timestamp,
                        meta=json.dumps(meta))


def host_version() -> str | None:
    try:
        return metadata.version("awr1843-ddm-host")
    except metadata.PackageNotFoundError:
        return None


def git_commit() -> str | None:
    """The short git commit of the host code, with "-dirty" for uncommitted changes; None outside git."""
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty"], cwd=Path(__file__).parent,
                              capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def load_capture(path: Path) -> Capture:
    """A capture of any format. Format 1 (int16 iq, no metadata) and older complex64
    `frames` captures load with every frame marked complete and unknown times; they left
    out incomplete frames, so their frames are not evenly spaced in time."""
    with np.load(path) as data:
        if "iq" in data:
            iq = data["iq"]
        else:  # complex64 frames holding int16 values: exact
            iq = np.stack([data["frames"].real, data["frames"].imag], axis=-1).astype(np.int16)
        config = str(data["config"])
        if "meta" in data:
            return Capture(iq, config, data["complete"], data["timestamp"], json.loads(str(data["meta"])))
    count = len(iq)
    meta = {"format": 1, "mode": mode(parse_cfg(config)), "frames": count, "incomplete": None}
    return Capture(iq, config, np.ones(count, bool), np.full(count, np.nan), meta)


def spectrum(frames: np.ndarray) -> np.ndarray:
    """[..., chirp, rx, sample] -> complex [..., Doppler, rx, range]: plain FFTs over fast
    and slow time, no window."""
    return np.fft.fft(np.fft.fft(frames, axis=-1), axis=-3)
