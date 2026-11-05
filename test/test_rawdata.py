# SPDX-License-Identifier: MIT
"""Unit tests for raw capture data: frame shape, byte order, storage and spectrum axes; no hardware needed."""

from pathlib import Path

import numpy as np
import pytest

from ddm.cfg import (
    SPEED_OF_LIGHT,
    centre_frequency_hz,
    chirp_axes,
    chirp_period_us,
    parse_cfg,
    profile,
    raw_frame_shape,
)
from ddm.rawdata import iiqq_to_iq, iq_to_complex, load_capture, save_capture, spectrum

RAW_CFG = Path(__file__).parent / "data" / "raw.cfg"


def to_iiqq(iq: np.ndarray) -> bytes:
    """Inverse of iiqq_to_iq: Q0 Q1 I0 I1 Q2 Q3 I2 I3 ... per RX."""
    iiqq = np.empty((*iq.shape[:-1], 2 * iq.shape[-1]), dtype="<i2")
    iiqq[..., 0::4], iiqq[..., 1::4] = iq.imag[..., 0::2], iq.imag[..., 1::2]
    iiqq[..., 2::4], iiqq[..., 3::4] = iq.real[..., 0::2], iq.real[..., 1::2]
    return iiqq.tobytes()


def test_raw_frame_shape_from_profile() -> None:
    assert raw_frame_shape(parse_cfg(RAW_CFG.read_text())) == (128, 4, 256)


@pytest.mark.parametrize(("line", "replacement", "message"), [
    ("lvdsStreamCfg -1 0 1 0", "lvdsStreamCfg -1 0 0 0", "LVDS"),  # processed output
    ("lvdsStreamCfg -1 0 1 0", "lvdsStreamCfg -1 1 1 0", "LVDS"),  # header in the stream
    ("adcCfg 2 1", "adcCfg 2 0", "complex"),                       # real ADC samples
])
def test_raw_frame_shape_rejects_unsupported_streams(line: str, replacement: str, message: str) -> None:
    cfg = parse_cfg(RAW_CFG.read_text().replace(line, replacement))
    with pytest.raises(ValueError, match=message):
        raw_frame_shape(cfg)


def test_iiqq_byte_order() -> None:
    """Q0 Q1 I0 I1 from the capture card is (I0, Q0), (I1, Q1)."""
    data = np.array([1, 2, 3, 4], dtype="<i2").tobytes()
    iq = iiqq_to_iq(data, (1, 1, 2))
    assert iq.dtype == np.int16
    assert np.array_equal(iq, [[[[3, 1], [4, 2]]]])
    assert np.array_equal(iq_to_complex(iq), [[[3 + 1j, 4 + 2j]]])


def test_iiqq_round_trip() -> None:
    rng = np.random.default_rng(0)
    shape = (4, 2, 8)
    iq = (rng.integers(-2000, 2000, shape) + 1j * rng.integers(-2000, 2000, shape)).astype(np.complex64)
    complex_iq = iq_to_complex(iiqq_to_iq(to_iiqq(iq), shape))
    assert complex_iq.dtype == np.complex64
    assert np.array_equal(complex_iq, iq)


def test_capture_round_trip_is_bit_exact(tmp_path: Path) -> None:
    """Captures keep the int16 samples unchanged; older complex64 captures still load."""
    rng = np.random.default_rng(1)
    iq = rng.integers(-32768, 32768, (2, 4, 4, 8, 2), dtype=np.int16)
    save_capture(tmp_path / "new.npz", iq, "cfg text")
    frames, text = load_capture(tmp_path / "new.npz")
    assert text == "cfg text"
    assert np.array_equal(frames.real, iq[..., 0]) and np.array_equal(frames.imag, iq[..., 1])
    np.savez_compressed(tmp_path / "old.npz", frames=frames, config="cfg text")
    assert np.array_equal(load_capture(tmp_path / "old.npz")[0], frames)


def test_spectrum_is_unwindowed() -> None:
    rng = np.random.default_rng(2)
    frame = rng.standard_normal((16, 4, 32)) + 1j * rng.standard_normal((16, 4, 32))
    assert np.allclose(spectrum(frame), np.fft.fft(np.fft.fft(frame, axis=-1), axis=0))


def test_spectrum_axes_place_target_at_true_range_and_velocity() -> None:
    """200 samples and 30 loops (120 chirps): the plot axes follow the unpadded FFTs."""
    cfg = parse_cfg(RAW_CFG.read_text().replace("1 256 7200", "1 200 7200").replace("0 3 32 0", "0 3 30 0"))
    num_chirps, _, num_samples = raw_frame_shape(cfg)
    p = profile(cfg)
    distance_m, velocity_mps = 3.0, 1.5
    beat_hz = 2 * p["slope_mhz_per_us"] * 1e12 * distance_m / SPEED_OF_LIGHT
    wavelength_m = SPEED_OF_LIGHT / centre_frequency_hz(cfg)
    doppler_cycles = 2 * velocity_mps * chirp_period_us(cfg) * 1e-6 / wavelength_m  # per chirp
    n = np.arange(num_chirps)[:, None, None]
    t = np.arange(num_samples) / (p["sample_rate_ksps"] * 1e3)
    frame = np.exp(2j * np.pi * (beat_hz * t + doppler_cycles * n))

    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    doppler_bin, _, range_bin = np.unravel_index(np.abs(spectrum(frame)).argmax(), frame.shape)
    signed_bin = doppler_bin - num_chirps if doppler_bin >= num_chirps // 2 else doppler_bin
    assert range_bin * range_step == pytest.approx(distance_m, abs=range_step)
    assert signed_bin * velocity_step == pytest.approx(velocity_mps, abs=velocity_step)


def test_snapshot_plots_a_capture(tmp_path: Path) -> None:
    """ddm show --snapshot: load a capture and save its raw plot (no display needed)."""
    import matplotlib

    matplotlib.use("Agg")
    from ddm.view import snapshot

    cfg_text = RAW_CFG.read_text()
    shape = (1, *raw_frame_shape(parse_cfg(cfg_text)), 2)
    iq = np.random.default_rng(3).integers(-500, 500, shape, dtype=np.int16)
    save_capture(tmp_path / "c.npz", iq, cfg_text)
    frames, text = load_capture(tmp_path / "c.npz")
    snapshot(frames[0], parse_cfg(text), tmp_path / "c.png")
    assert (tmp_path / "c.png").stat().st_size > 0
