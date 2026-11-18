# SPDX-License-Identifier: MIT
"""Unit tests for 'ddm capture' with a simulated radar and capture card."""

from __future__ import annotations

import argparse
import contextlib
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from ddm import cli, dca
from ddm.cfg import parse_cfg, raw_frame_shape
from ddm.rawdata import load_capture

DATA = Path(__file__).parent / "data"
RAW = (DATA / "raw.cfg").read_text()
SHAPE = raw_frame_shape(parse_cfg(RAW))


def fake_stream(count: int, then: BaseException | None = None) -> Callable[..., Iterator[dca.Frame]]:
    """A capture() that yields count random frames, the second one incomplete, then raises then."""
    def capture(*_args: object) -> Iterator[dca.Frame]:
        rng = np.random.default_rng(0)
        for k in range(count):
            yield dca.Frame(rng.integers(-2**15, 2**15, (*SHAPE, 2), dtype=np.int16), 1e9 + k, k != 1)
        if then is not None:
            raise then
    return capture


def run_capture(monkeypatch: pytest.MonkeyPatch, out: Path, received: int,
                then: BaseException | None = None) -> None:
    monkeypatch.setattr(dca, "capture", fake_stream(received, then))
    monkeypatch.setattr(dca, "open_capture_card", lambda: None)
    cli.cmd_capture(argparse.Namespace(profile=DATA / "raw.cfg", tdm=False, cli="", frames=3, out=out))


def expected(count: int) -> np.ndarray:
    return np.stack([frame.iq for frame in fake_stream(count)()])


@pytest.mark.parametrize("received", [3, 2])  # all requested frames, or a stream that ends early
def test_capture_writes_every_received_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                             caplog: pytest.LogCaptureFixture, received: int) -> None:
    out = tmp_path / "c.npz"
    run_capture(monkeypatch, out, received)
    cap = load_capture(out)
    assert np.array_equal(cap.iq, expected(received))
    assert cap.complete.tolist() == [True, False, True][:received]
    assert list(tmp_path.iterdir()) == [out]  # the scratch file is gone
    assert ("timed out after 2 of 3" in caplog.text) == (received < 3)


def test_capture_without_frames_leaves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TimeoutError, match="no frames"):
        run_capture(monkeypatch, tmp_path / "c.npz", 0)
    assert list(tmp_path.iterdir()) == []


def test_failed_stop_saves_the_frames_then_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def capture(*args: object) -> Iterator[dca.Frame]:
        try:
            yield from fake_stream(3)(*args)
        finally:
            raise RuntimeError("sensorStop failed")  # on close, after every frame arrived

    monkeypatch.setattr(dca, "capture", capture)
    monkeypatch.setattr(dca, "open_capture_card", lambda: None)
    out = tmp_path / "c.npz"
    with pytest.raises(RuntimeError, match="sensorStop failed"):
        cli.cmd_capture(argparse.Namespace(profile=DATA / "raw.cfg", tdm=False, cli="", frames=3, out=out))
    assert np.array_equal(load_capture(out).iq, expected(3))


@pytest.mark.parametrize("then", [OSError("cable"), ValueError("bad frame")])
def test_any_error_saves_the_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                    then: Exception) -> None:
    out = tmp_path / "c.npz"
    with pytest.raises(type(then)):
        run_capture(monkeypatch, out, 2, then)
    assert len(load_capture(out).iq) == 2


def test_ctrl_c_saves_the_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                 caplog: pytest.LogCaptureFixture) -> None:
    out = tmp_path / "c.npz"
    run_capture(monkeypatch, out, 2, KeyboardInterrupt())
    assert np.array_equal(load_capture(out).iq, expected(2))
    assert "interrupted after 2 of 3" in caplog.text


def test_card_stops_when_the_radar_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("xwr.capture._fast")
    calls = []

    class Card:
        def stop(self) -> None:
            calls.append("card stop")

        def flush(self) -> None: ...
        def start(self) -> None: ...

        def stream(self, shape: list[int]) -> Iterator[object]:
            yield argparse.Namespace(data=bytes(int(np.prod(shape)) * 2), timestamp=1e9, complete=True)

    def sensor_stop(*_args: object, **_kwargs: object) -> None:
        if calls:  # the stop before the capture succeeds
            raise OSError("serial port gone")
        calls.append("first stop")

    monkeypatch.setattr(dca, "open_cli", lambda _port: contextlib.nullcontext())
    monkeypatch.setattr(dca, "send_config", lambda *_args: None)
    monkeypatch.setattr(dca, "sensor_stop", sensor_stop)
    stream = dca.capture(RAW, "", Card())
    assert next(stream).iq.shape == (*SHAPE, 2)
    with pytest.raises(OSError, match="serial port gone"):
        next(stream)
    assert calls[-1] == "card stop"
