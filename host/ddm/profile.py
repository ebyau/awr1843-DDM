# SPDX-License-Identifier: MIT
"""TOML profiles: a short description of the chirp, MIMO mode and frame, rendered to the TI
.cfg text the raw-data firmware reads. See docs/configuration.md for the format.
"""

from __future__ import annotations

import copy
import logging
import tomllib
from pathlib import Path
from typing import Any

from .cfg import (
    PROFILE_FIELDS,
    Config,
    cfg_args,
    chirp_period_us,
    chirps_per_frame,
    ddm_params,
    doppler_bins,
    is_tdm,
    max_velocity,
    parse_cfg,
    range_axis,
)
from .cfg import profile as chirp_profile
from .limits import check

log = logging.getLogger(__name__)

Profile = dict[str, Any]

DEFAULTS: Profile = {
    "chirp": {"profile_id": 0, "tx_power_backoff": 0, "tx_phase_shifter": 0, "tx_start_us": 1,
              "hpf1_corner": 0, "hpf2_corner": 0},
    "mimo": {"tx": [0, 1, 2], "rx": [0, 1, 2, 3], "bands": 4, "tdm": False},
    "frame": {},
    "extra": {"lines": []},
}
REQUIRED = {
    "chirp": set(PROFILE_FIELDS) - set(DEFAULTS["chirp"]),
    "frame": {"loops", "period_ms"},
}


def read(path: Path) -> Profile:
    """A TOML profile with defaults filled; raises ValueError if it is malformed."""
    with path.open("rb") as f:
        profile = merge(DEFAULTS, tomllib.load(f))
    for table, keys in profile.items():
        if table == "description":
            continue
        if table not in DEFAULTS:
            raise ValueError(f"{path}: unknown table [{table}]")
        known = set(DEFAULTS[table]) | REQUIRED.get(table, set())
        if unknown := set(keys) - known:
            raise ValueError(f"{path}: unknown key(s) in [{table}]: {', '.join(sorted(unknown))}")
        if missing := REQUIRED.get(table, set()) - set(keys):
            raise ValueError(f"{path}: [{table}] needs {', '.join(sorted(missing))}")
    return profile


def merge(base: Profile, update: Profile) -> Profile:
    """base with each table updated key by key from update; other values replaced."""
    merged = copy.deepcopy(base)  # callers may change the result; DEFAULTS must not change
    for key, value in update.items():
        merged[key] = {**merged.get(key, {}), **value} if isinstance(value, dict) else value
    return merged


def fmt(value: float | bool) -> str:
    """A number as the CLI expects it: integers without a decimal point."""
    if isinstance(value, bool) or float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def mask(indices: list[int]) -> int:
    return sum(1 << i for i in set(indices))


def render(profile: Profile, source: str = "") -> str:
    """The TI .cfg text of a profile from read(): the radar streams raw ADC data over LVDS."""
    chirp, mimo, frame = (profile[t] for t in ("chirp", "mimo", "frame"))
    tx_mask = mask(mimo["tx"])
    # TDM: one chirp per TX, in the listed order. DDM: one chirp per sub-band, all TX on each.
    rows = [1 << tx for tx in mimo["tx"]] if mimo["tdm"] else [tx_mask] * mimo["bands"]
    lines = [
        "sensorStop", "flushCfg", "dfeDataOutputMode 1", f"channelCfg {mask(mimo['rx'])} {tx_mask} 0",
        "adcCfg 2 1", "adcbufCfg -1 0 1 1 1", "lowPower 0 0",
        "profileCfg " + " ".join(fmt(chirp[name]) for name in PROFILE_FIELDS),
        *(f"chirpCfg {i} {i} 0 0 0 0 0 {row}" for i, row in enumerate(rows)),
        f"frameCfg 0 {len(rows) - 1} {frame['loops']} 0 {fmt(frame['period_ms'])} 1 0",
        "lvdsStreamCfg -1 0 1 0",
        "calibData 0 0 0",
        # TDM sends ddmCfg 0: the firmware keeps a ddmCfg until a start succeeds
        f"ddmCfg {0 if mimo['tdm'] else mimo['bands']}",
    ]
    lines = apply_extra(lines, profile["extra"]["lines"])
    header = [f"% Generated from {source} by 'ddm cfg'; edit the profile, not this file."] if source else []
    header += [f"% {line}" for line in profile.get("description", "").strip().splitlines()]
    return "\n".join([*header, *lines, "sensorStart"]) + "\n"


def apply_extra(lines: list[str], extra: list[str]) -> list[str]:
    """Each command in extra replaces all generated lines of that command, at the place of
    the first; commands not generated are added at the end."""
    extra = [line for line in extra if line.strip()]
    if any(line.split()[0] == "sensorStart" for line in extra):
        raise ValueError("[extra] must not contain sensorStart; it is always the last line")
    by_command: dict[str, list[str]] = {}
    for line in extra:
        by_command.setdefault(line.split()[0], []).append(line)
    result = []
    for line in lines:
        command = line.split()[0] if line.strip() else ""
        if command in by_command:
            result += by_command.pop(command)
        elif not any(command == extra_line.split()[0] for extra_line in extra):
            result.append(line)
    return result + [line for group in by_command.values() for line in group]


def load(path: Path, allow_tdm: bool = False) -> tuple[str, Config]:
    """The .cfg text and parsed commands of a profile: a .toml profile, rendered
    (hardware-limit violations are errors), or a TI .cfg file, sent as it is
    (violations are logged as warnings).

    A .cfg file without ddmCfg would run TDM; it is refused unless allow_tdm, so TDM data
    never ends up in a DDM dataset by accident. A .toml profile chooses with [mimo] tdm.
    """
    if path.suffix == ".toml":
        text = render(read(path), path.name)
        cfg = parse_cfg(text)
        if problems := check(cfg):
            raise ValueError(f"{path}: " + "; ".join(problems))
    else:
        text = path.read_text()
        cfg = parse_cfg(text)
        try:
            problems = check(cfg)
        except ValueError as err:  # e.g. advanced-frame files without frameCfg
            problems = [f"limits not checked ({err})"]
        for problem in problems:
            log.warning("%s: %s", path, problem)
        if "ddmCfg" not in cfg and not allow_tdm:
            raise ValueError(f"{path} has no ddmCfg, so the radar would run TDM (one TX per chirp). "
                             "Add 'ddmCfg 4' for DDM, or 'ddmCfg 0' (or --tdm) if TDM is intended")
    return text, cfg


def derived(cfg: Config) -> dict[str, float]:
    """Numbers that follow from a configuration, by description with unit."""
    bands, _ = ddm_params(cfg)
    num_range, range_step = range_axis(cfg)
    num_doppler = doppler_bins(cfg)
    num_rx = int(cfg_args(cfg, "channelCfg")[0]).bit_count()
    v_max = max_velocity(cfg)
    frame_rate = 1e3 / float(cfg_args(cfg, "frameCfg")[4])
    frame_bytes = chirps_per_frame(cfg) * num_rx * int(chirp_profile(cfg)["samples"]) * 4  # complex 16-bit
    numbers = {
        "chirp period (us)": chirp_period_us(cfg),
        "chirp burst (ms)": chirps_per_frame(cfg) * chirp_period_us(cfg) / 1e3,
        "frame rate (Hz)": frame_rate,
        "range step (m)": range_step,
        "range max (m)": num_range * range_step,
        "v max (m/s)": v_max,
        "velocity step (m/s)": 2 * v_max / num_doppler,
    }
    if not is_tdm(cfg):
        numbers["sub-band span (m/s)"] = 2 * v_max / bands
    numbers["raw frame (KB)"] = frame_bytes / 1024
    numbers["raw data rate (MB/s)"] = frame_bytes * frame_rate / 1e6
    return numbers
