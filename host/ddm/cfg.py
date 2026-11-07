# SPDX-License-Identifier: MIT
"""Parse TI mmw demo .cfg text and read the radar parameters it sets."""

from __future__ import annotations

SPEED_OF_LIGHT = 299_792_458.0

# profileCfg arguments in order; the names (with units) are also the [chirp] keys of a TOML profile.
PROFILE_FIELDS = (
    "profile_id", "start_ghz", "idle_us", "adc_start_us", "ramp_end_us", "tx_power_backoff",
    "tx_phase_shifter", "slope_mhz_per_us", "tx_start_us", "samples", "sample_rate_ksps",
    "hpf1_corner", "hpf2_corner", "rx_gain_db",
)

Config = dict[str, list[list[str]]]


def parse_cfg(text: str) -> Config:
    """CLI command -> the arguments of each of its occurrences, comments skipped."""
    commands: Config = {}
    for line in text.splitlines():
        fields = line.split()
        if fields and not fields[0].startswith("%"):
            commands.setdefault(fields[0], []).append(fields[1:])
    return commands


def cfg_args(cfg: Config, command: str) -> list[str]:
    """Arguments of the first occurrence of a command."""
    if command not in cfg:
        raise ValueError(f"configuration has no {command}")
    return cfg[command][0]


def profile(cfg: Config) -> dict[str, float]:
    """profileCfg arguments by name (PROFILE_FIELDS)."""
    args = cfg_args(cfg, "profileCfg")
    return {name: float(value) for name, value in zip(PROFILE_FIELDS, args, strict=False)}


def range_axis(cfg: Config) -> tuple[int, float]:
    """Number of range bins and metres per bin, from profileCfg: the host's range FFT has
    one bin per ADC sample (no zero padding)."""
    p = profile(cfg)
    num_bins = int(p["samples"])
    slope_hz_per_s = abs(p["slope_mhz_per_us"]) * 1e12  # negative slopes give the same range axis
    return num_bins, SPEED_OF_LIGHT * p["sample_rate_ksps"] * 1e3 / (2 * slope_hz_per_s * num_bins)


def chirp_period_us(cfg: Config) -> float:
    p = profile(cfg)
    return p["idle_us"] + p["ramp_end_us"]


def sampling_end_us(cfg: Config) -> float:
    """End of ADC sampling within the ramp."""
    p = profile(cfg)
    return p["adc_start_us"] + p["samples"] / (p["sample_rate_ksps"] / 1e3)


def centre_frequency_hz(cfg: Config) -> float:
    """RF frequency at the middle of the sampled part of the chirp."""
    p = profile(cfg)
    middle_us = (p["adc_start_us"] + sampling_end_us(cfg)) / 2
    return (p["start_ghz"] * 1e3 + p["slope_mhz_per_us"] * middle_us) * 1e6


def chirps_per_loop(cfg: Config) -> int:
    chirp_start, chirp_end = (int(f) for f in cfg_args(cfg, "frameCfg")[:2])
    return chirp_end - chirp_start + 1


def chirps_per_frame(cfg: Config) -> int:
    return chirps_per_loop(cfg) * int(cfg_args(cfg, "frameCfg")[2])


def ddm_params(cfg: Config) -> tuple[int, int]:
    """(Doppler sub-bands, TX antennas per chirp) from ddmCfg and the first chirpCfg;
    0 sub-bands means TDM."""
    bands = int(cfg["ddmCfg"][0][0]) if "ddmCfg" in cfg else 0
    return bands, int(cfg_args(cfg, "chirpCfg")[7]).bit_count()


def is_tdm(cfg: Config) -> bool:
    return ddm_params(cfg)[0] == 0


def mode(cfg: Config) -> str:
    """The MIMO mode tag: ddm, or tdm without ddmCfg (the TX take turns, one per chirp)."""
    return "tdm" if is_tdm(cfg) else "ddm"


def describe_mode(cfg: Config) -> str:
    """The MIMO mode in words, e.g. "DDM, 4 sub-bands" or "TDM"."""
    bands, _ = ddm_params(cfg)
    return "TDM" if is_tdm(cfg) else f"DDM, {bands} sub-bands"


def doppler_bins(cfg: Config) -> int:
    """Doppler FFT size (no zero padding): every chirp with DDM, one chirp per loop with TDM."""
    if is_tdm(cfg):
        return int(cfg_args(cfg, "frameCfg")[2])
    return chirps_per_frame(cfg)


def chirp_axes(cfg: Config, num_chirps: int) -> tuple[float, float]:
    """Metres per range bin and m/s per Doppler bin when num_chirps chirps, one chirp
    period apart, span the Doppler FFT (with TDM: loops x TX)."""
    velocity_step = SPEED_OF_LIGHT / (2 * centre_frequency_hz(cfg) * num_chirps * chirp_period_us(cfg) * 1e-6)
    return range_axis(cfg)[1], velocity_step


def max_velocity(cfg: Config) -> float:
    """Unambiguous radial velocity in m/s: lambda / (4 * chirp period), times the TX count with TDM."""
    chirps = chirps_per_loop(cfg) if is_tdm(cfg) else 1
    return SPEED_OF_LIGHT / (4 * centre_frequency_hz(cfg) * chirps * chirp_period_us(cfg) * 1e-6)


def raw_frame_shape(cfg: Config) -> tuple[int, int, int]:
    """(chirps, rx, samples) of one raw frame; every chirp carries all enabled RX."""
    if cfg_args(cfg, "adcCfg")[1] == "0":
        raise ValueError("raw capture needs complex ADC output (adcCfg 2 1)")
    if cfg_args(cfg, "lvdsStreamCfg")[1:4] != ["0", "1", "0"]:
        raise ValueError("raw capture needs headerless ADC data on LVDS (lvdsStreamCfg -1 0 1 0)")
    # The decode (rawdata.iiqq_to_iq) assumes complex output, Q before I and RX not interleaved
    if cfg_args(cfg, "adcbufCfg")[1:4] != ["0", "1", "1"]:
        raise ValueError("raw capture needs adcbufCfg -1 0 1 1 1 (complex, Q first, RX not interleaved); "
                         "other layouts would decode with I/Q swapped or RX scrambled")
    num_rx = int(cfg_args(cfg, "channelCfg")[0]).bit_count()
    return chirps_per_frame(cfg), num_rx, int(profile(cfg)["samples"])
