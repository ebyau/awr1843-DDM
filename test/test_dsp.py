# SPDX-License-Identifier: MIT
"""Unit tests for raw DDM and TDM capture decoding; no hardware needed."""

from pathlib import Path

import numpy as np
import pytest

from ddm.cfg import (
    SPEED_OF_LIGHT,
    centre_frequency_hz,
    chirp_axes,
    chirp_period_us,
    doppler_bins,
    mimo_params,
    parse_cfg,
    profile,
    range_axis,
    raw_frame_shape,
)
from ddm.dsp import (
    ddm_virtual_array,
    decode_frame,
    doppler_spectrum,
    find_targets,
    fold,
    range_doppler_power,
    remove_static,
    signed_doppler_bin,
    spectrum,
    tdm_spectrum,
    tdm_virtual_array,
    tx0_band,
)
from ddm.rawdata import iiqq_to_iq, iq_to_complex, load_capture, save_capture

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


def test_spectrum_is_unwindowed_unless_asked() -> None:
    rng = np.random.default_rng(2)
    frame = rng.standard_normal((16, 4, 32)) + 1j * rng.standard_normal((16, 4, 32))
    assert np.allclose(spectrum(frame), np.fft.fft(np.fft.fft(frame, axis=-1), axis=0))
    windowed = frame * np.hanning(32) * np.hanning(16)[:, None, None]
    assert np.allclose(doppler_spectrum(frame), spectrum(windowed))


def test_chirp_axes_match_firmware_profile() -> None:
    range_step, velocity_step = chirp_axes(parse_cfg(RAW_CFG.read_text()), 128)
    assert range_step == pytest.approx(0.0422, rel=1e-2)
    assert velocity_step == pytest.approx(0.322, rel=1e-2)


@pytest.mark.parametrize("doppler_bin", [0, 5, 31, 40, 100, 127])
def test_simulated_ddm_target_is_resolved(doppler_bin: int) -> None:
    """Three phase-coded TX copies of one target: TX k lands k sub-bands above TX0."""
    chirps, rx, samples, bands, num_tx, range_bin = 128, 4, 256, 4, 3, 60
    n = np.arange(chirps)[:, None, None]
    s = np.arange(samples)
    tone = sum(np.exp(2j * np.pi * (doppler_bin * n / chirps + k * n / bands + range_bin * s / samples))
               for k in range(num_tx))
    rng = np.random.default_rng(1)
    noise = rng.normal(size=(chirps, rx, samples)) + 1j * rng.normal(size=(chirps, rx, samples))
    power = range_doppler_power((tone + 0.1 * noise)[None])

    (target_range, folded_bin), *_ = find_targets(fold(power, bands))
    width = chirps // bands
    tx0 = tx0_band(power[target_range, folded_bin::width], num_tx)
    assert target_range == range_bin
    assert signed_doppler_bin(folded_bin, tx0, width, chirps) == (doppler_bin + 64) % chirps - 64


def test_target_at_true_range_and_velocity_without_power_of_two_sizes() -> None:
    """200 samples and 30 loops (120 chirps): the axes follow the unpadded FFTs."""
    cfg = parse_cfg(RAW_CFG.read_text().replace("1 256 7200", "1 200 7200").replace("0 3 32 0", "0 3 30 0"))
    num_chirps, _, num_samples = raw_frame_shape(cfg)
    assert (num_chirps, num_samples) == (120, 200) == (doppler_bins(cfg), range_axis(cfg)[0])
    p = profile(cfg)
    distance_m, velocity_mps = 3.0, 1.5
    beat_hz = 2 * p["slope_mhz_per_us"] * 1e12 * distance_m / SPEED_OF_LIGHT
    wavelength_m = SPEED_OF_LIGHT / centre_frequency_hz(cfg)
    doppler_cycles = 2 * velocity_mps * chirp_period_us(cfg) * 1e-6 / wavelength_m  # per chirp
    n = np.arange(num_chirps)[:, None, None]
    t = np.arange(num_samples) / (p["sample_rate_ksps"] * 1e3)
    frame = sum(np.exp(2j * np.pi * (beat_hz * t + doppler_cycles * n + k * n / 4)) for k in range(3))

    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    power = range_doppler_power(np.repeat(frame, 4, axis=1)[None])
    (range_bin, folded_bin), *_ = find_targets(fold(power, 4))
    width = num_chirps // 4
    tx0 = tx0_band(power[range_bin, folded_bin::width], 3)
    assert range_bin * range_step == pytest.approx(distance_m, abs=range_step)
    assert signed_doppler_bin(folded_bin, tx0, width, num_chirps) * velocity_step == pytest.approx(
        velocity_mps, abs=velocity_step)


def ddm_frame(doppler_bin: int, range_bin: int, antenna_phase: np.ndarray) -> np.ndarray:
    """One noiseless DDM frame [chirp, rx, sample]: 3 phase-coded TX, 4 sub-bands."""
    n = np.arange(128)[:, None, None]
    s = np.arange(256)
    return sum(np.exp(2j * np.pi * (doppler_bin * n / 128 + k * n / 4 + range_bin * s / 256)
                      + 1j * antenna_phase[k][None, :, None]) for k in range(3))


def test_remove_static_removes_every_tx_copy_of_static_targets() -> None:
    phase = np.zeros((3, 4))
    static = ddm_frame(0, 20, phase)
    moving = ddm_frame(-10, 40, phase)
    power = (np.abs(doppler_spectrum(remove_static(static + moving, 4))) ** 2).sum(axis=1)
    assert power[[0, 32, 64, 96], 20].max() < 1e-6 * power.max()
    assert power[(-10 + 128) % 128, 40] == pytest.approx(power.max(), rel=0.01)  # moving target kept


def test_ddm_virtual_array_separates_tx_copies() -> None:
    phase = np.random.default_rng(2).uniform(-np.pi, np.pi, (3, 4))
    virtual, tx0_bin = ddm_virtual_array(doppler_spectrum(ddm_frame(-10, 20, phase)), 4, 3)
    folded = (-10) % 32
    assert tx0_bin[folded, 20] == (-10) % 128
    measured = np.angle(virtual[folded, 20] / virtual[folded, 20, 0, 0])
    expected = phase - phase[0, 0]
    assert np.allclose(np.angle(np.exp(1j * (measured - expected))), 0, atol=1e-3)


def test_mimo_mode_from_configuration() -> None:
    data = Path(__file__).parent / "data"
    assert mimo_params(parse_cfg((data / "raw.cfg").read_text())) == (4, 3)
    assert mimo_params(parse_cfg((data / "tdm.cfg").read_text())) == (0, 3)
    with pytest.raises(ValueError, match="more sub-bands"):
        mimo_params(parse_cfg((data / "raw.cfg").read_text().replace("ddmCfg 4", "ddmCfg 3")))


def tdm_frame(doppler_bin: int, range_bin: int, antenna_phase: np.ndarray, loops: int = 32) -> np.ndarray:
    """One noiseless TDM frame [chirp, rx, sample]: chirps TX0, TX1, TX2 in every loop; the
    target moves 2 pi doppler_bin / loops per loop, so a third of that between TX chirps."""
    num_tx = antenna_phase.shape[0]
    n = np.arange(loops * num_tx)
    s = np.arange(256)
    motion = np.exp(2j * np.pi * doppler_bin * n / (loops * num_tx))[:, None, None]
    antenna = np.exp(1j * antenna_phase[n % num_tx])[:, :, None]
    return motion * antenna * np.exp(2j * np.pi * range_bin * s / 256)


@pytest.mark.parametrize("doppler_bin", [-16, -5, 0, 7, 15])
def test_tdm_virtual_array_compensates_motion(doppler_bin: int) -> None:
    phase = np.random.default_rng(3).uniform(-np.pi, np.pi, (3, 4))
    spectrum = tdm_spectrum(tdm_frame(doppler_bin, 20, phase), 3)
    assert spectrum.shape == (32, 3, 4, 256)
    power = (np.abs(spectrum) ** 2).sum(axis=(1, 2))
    assert np.unravel_index(np.argmax(power), power.shape) == (doppler_bin % 32, 20)
    virtual = tdm_virtual_array(spectrum)[doppler_bin % 32, 20]
    measured = np.angle(virtual / virtual[0, 0])
    expected = phase - phase[0, 0]
    assert np.allclose(np.angle(np.exp(1j * (measured - expected))), 0, atol=1e-3)


def test_tdm_decode_frame_places_target() -> None:
    phase = np.zeros((3, 4))
    frame = tdm_frame(-5, 40, phase) + tdm_frame(0, 20, phase)
    raw, velocity, azimuth = decode_frame(frame, 0, 3, static_loop=3)
    assert raw.shape == velocity.shape == (256, 32)
    assert np.unravel_index(np.argmax(velocity), velocity.shape) == (40, 16 - 5)  # zero velocity centred
    assert raw[20, 0] < 1e-6 * raw.max()  # static target removed
    assert np.argmax(azimuth[40]) == 64  # boresight
