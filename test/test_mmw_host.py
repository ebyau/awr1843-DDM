# SPDX-License-Identifier: MIT
"""Unit tests for frame decoding in host/mmw_host.py. Run: uv run pytest"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest

from mmw_host import (
    HEADER,
    MAGIC,
    POINT,
    TLV_DETECTED_POINTS,
    TLV_HEADER,
    FrameError,
    range_axis,
    read_frame,
)


class FakePort(io.BytesIO):
    """Byte stream with the two pyserial reads read_frame uses; reads past the end return short."""

    def read_until(self, expected: bytes = b"\n") -> bytes:
        data = self.getvalue()
        end = data.find(expected, self.tell())
        stop = len(data) if end < 0 else end + len(expected)
        chunk = data[self.tell():stop]
        self.seek(stop)
        return chunk


def make_frame(number: int, tlvs: list[tuple[int, bytes]], total_len: int | None = None) -> bytes:
    body = b"".join(TLV_HEADER.pack(tlv_type, len(payload)) + payload for tlv_type, payload in tlvs)
    length = HEADER.size + len(body) if total_len is None else total_len
    return HEADER.pack(MAGIC, 0, length, 0, number, 0, 0, len(tlvs), 0) + body


def points_payload(*points: tuple[float, float, float, float]) -> bytes:
    return b"".join(POINT.pack(*p) for p in points)


def test_decodes_points_and_other_tlvs() -> None:
    frame = make_frame(7, [(TLV_DETECTED_POINTS, points_payload((1.0, 2.0, 0.5, -0.25))), (6, b"\x01\x02")])
    decoded = read_frame(FakePort(b"noise" + frame))

    assert decoded.number == 7
    assert decoded.tlvs[6] == b"\x01\x02"
    assert [(p.x, p.y, p.z, p.v) for p in decoded.points] == [(1.0, 2.0, 0.5, -0.25)]


def test_frame_without_points_has_empty_point_list() -> None:
    assert read_frame(FakePort(make_frame(1, [(6, b"stats")]))).points == []


def test_tlv_longer_than_frame_raises_frame_error() -> None:
    frame = bytearray(make_frame(2, [(5, b"abcd")]))
    struct.pack_into("<I", frame, HEADER.size + 4, 1_000_000)  # corrupt the TLV length
    with pytest.raises(FrameError):
        read_frame(FakePort(bytes(frame)))


def test_implausible_frame_length_raises_frame_error() -> None:
    with pytest.raises(FrameError):
        read_frame(FakePort(make_frame(3, [], total_len=10)))


def test_next_frame_inside_body_raises_frame_error_then_resyncs() -> None:
    swallowed = make_frame(4, [(5, MAGIC + b"12345678")])
    good = make_frame(5, [(6, b"ok")])
    port = FakePort(swallowed + good)

    with pytest.raises(FrameError):
        read_frame(port)
    assert read_frame(port).number == 5


def test_missing_or_truncated_frame_times_out() -> None:
    with pytest.raises(TimeoutError):
        read_frame(FakePort(b"no frame here"))
    with pytest.raises(TimeoutError):
        read_frame(FakePort(make_frame(6, [(6, b"payload")])[:-3]))


def test_range_axis_matches_profile(tmp_path: Path) -> None:
    cfg = tmp_path / "profile.cfg"
    cfg.write_text("% comment\nprofileCfg 0 77 7 3 39 0 0 100 1 256 7200 0 0 30\n")
    num_bins, step = range_axis(cfg)

    assert num_bins == 256
    assert step == pytest.approx(3e8 * 7.2e6 / (2 * 100e12 * 256))
