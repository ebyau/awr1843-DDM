# SPDX-License-Identifier: MIT
"""TOML profiles: a short description of the chirp, MIMO mode, frame and outputs, rendered
to the TI .cfg text the firmware reads.

A profile may name a parent with extends = "other.toml" (one level): each of its tables
updates the parent's table of the same name. See docs/configuration.md for the format.
"""

from __future__ import annotations

import logging
import math
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
from .limits import CFAR_MATRIX_MAX_BYTES, check

log = logging.getLogger(__name__)

Profile = dict[str, Any]

DEFAULTS: Profile = {
    "chirp": {"profile_id": 0, "tx_power_backoff": 0, "tx_phase_shifter": 0, "tx_start_us": 1,
              "hpf1_corner": 0, "hpf2_corner": 0},
    "mimo": {"tx": [0, 1, 2], "rx": [0, 1, 2, 3], "bands": 4, "tdm": False},
    "frame": {},
    "cfar": {"range_m": [0.25, 15]},
    "output": {"point_cloud": True, "range_profile": True, "stats": True, "heatmap": False,
               "raw_lvds": False},
    "extra": {"lines": []},
}
REQUIRED = {
    "chirp": set(PROFILE_FIELDS) - set(DEFAULTS["chirp"]),
    "frame": {"loops", "period_ms"},
}
OPTIONAL = {"cfar": {"doppler_mps"}}
DOPPLER_MARGIN = 1.025  # CFAR Doppler window over the unambiguous velocity, rounded up to 0.1 m/s

# Commands the profile format does not describe, as in TI's profile_3d_aop.cfg; [extra] overrides them.
CFAR = ["cfarCfg -1 0 2 8 4 3 0 15.0 0", "cfarCfg -1 1 0 4 2 3 1 15.0 0", "multiObjBeamForming -1 1 0.5",
        "calibDcRangeSig -1 0 -5 8 256", "clutterRemoval -1 0", "",
        "compRangeBiasAndRxChanPhase 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0",
        "measureRangeBiasAndRxChanPhase 0 1. 0.2", "", "aoaFovCfg -1 -90 90 -90 90"]
MONITORS = ["extendedMaxVelocity -1 0", "", "CQRxSatMonitor 0 3 11 121 0", "CQSigImgMonitor 0 127 8",
            "analogMonitor 0 0"]


def read(path: Path) -> Profile:
    """A TOML profile with its parent merged in and defaults filled; raises ValueError if
    it is malformed."""
    with path.open("rb") as f:
        profile = tomllib.load(f)
    parent_name = profile.pop("extends", None)
    if parent_name is not None:
        with (path.parent / parent_name).open("rb") as f:
            parent = tomllib.load(f)
        if "extends" in parent:
            raise ValueError(f"{path}: {parent_name} extends another profile; only one level is allowed")
        profile = merge(parent, profile)
    profile = merge(DEFAULTS, profile)
    for table, keys in profile.items():
        if table == "description":
            continue
        if table not in DEFAULTS:
            raise ValueError(f"{path}: unknown table [{table}]")
        known = set(DEFAULTS[table]) | REQUIRED.get(table, set()) | OPTIONAL.get(table, set())
        if unknown := set(keys) - known:
            raise ValueError(f"{path}: unknown key(s) in [{table}]: {', '.join(sorted(unknown))}")
        if missing := REQUIRED.get(table, set()) - set(keys):
            raise ValueError(f"{path}: [{table}] needs {', '.join(sorted(missing))}")
    return profile


def merge(base: Profile, update: Profile) -> Profile:
    """base with each table updated key by key from update; other values replaced."""
    merged = dict(base)
    for key, value in update.items():
        merged[key] = {**base.get(key, {}), **value} if isinstance(value, dict) else value
    return merged


def fmt(value: float | bool) -> str:
    """A number as the CLI expects it: integers without a decimal point."""
    if isinstance(value, bool) or float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def mask(indices: list[int]) -> int:
    return sum(1 << i for i in set(indices))


def render(profile: Profile, source: str = "") -> str:
    """The TI .cfg text of a profile from read()."""
    chirp, mimo, frame, cfar, out = (profile[t] for t in ("chirp", "mimo", "frame", "cfar", "output"))
    tx_mask = mask(mimo["tx"])
    # TDM: one chirp per TX, in the listed order. DDM: one chirp per sub-band, all TX on each.
    rows = [1 << tx for tx in mimo["tx"]] if mimo["tdm"] else [tx_mask] * mimo["bands"]
    channel = f"channelCfg {mask(mimo['rx'])} {tx_mask} 0"
    chirps = [f"chirpCfg {i} {i} 0 0 0 0 0 {row}" for i, row in enumerate(rows)]
    timing = [
        "profileCfg " + " ".join(fmt(chirp[name]) for name in PROFILE_FIELDS),
        *chirps,
        f"frameCfg 0 {len(rows) - 1} {frame['loops']} 0 {fmt(frame['period_ms'])} 1 0",
    ]
    ddm = [] if mimo["tdm"] else [f"ddmCfg {mimo['bands']}"]
    doppler = cfar.get("doppler_mps")
    if doppler is None:
        v = math.ceil(max_velocity(parse_cfg("\n".join([channel, *timing, *ddm]))) * DOPPLER_MARGIN * 10) / 10
        doppler = [-v, v]
    gui = [out["point_cloud"], out["range_profile"], 0, 0, out["heatmap"], out["stats"]]

    lines = [
        "sensorStop", "flushCfg", "dfeDataOutputMode 1", channel, "adcCfg 2 1", "adcbufCfg -1 0 1 1 1",
        "lowPower 0 0", *timing,
        "guiMonitor -1 " + " ".join(fmt(flag) for flag in gui),
        *CFAR,
        "cfarFovCfg -1 0 " + " ".join(fmt(r) for r in cfar["range_m"]),
        "cfarFovCfg -1 1 " + " ".join(fmt(d) for d in doppler),
        "", *MONITORS,
        f"lvdsStreamCfg -1 0 {fmt(out['raw_lvds'])} 0",
        "calibData 0 0 0",
        *ddm,
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


def load(path: Path) -> tuple[str, Config]:
    """The .cfg text and parsed commands of a profile: a .toml profile (hardware-limit
    violations are errors) or a TI .cfg file (violations are logged as warnings)."""
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
    return text, cfg


def derived(cfg: Config) -> dict[str, float]:
    """Numbers that follow from a configuration, by description with unit."""
    bands, _ = ddm_params(cfg)
    num_range, range_step = range_axis(cfg)
    num_doppler = doppler_bins(cfg)
    num_rx = int(cfg_args(cfg, "channelCfg")[0]).bit_count()
    v_max = max_velocity(cfg)
    folded = num_doppler if is_tdm(cfg) else num_doppler // bands
    numbers = {
        "chirp period (us)": chirp_period_us(cfg),
        "chirp burst (ms)": chirps_per_frame(cfg) * chirp_period_us(cfg) / 1e3,
        "frame rate (Hz)": 1e3 / float(cfg_args(cfg, "frameCfg")[4]),
        "range step (m)": range_step,
        "range max (m)": num_range * range_step,
        "v max (m/s)": v_max,
        "velocity step (m/s)": 2 * v_max / num_doppler,
    }
    if not is_tdm(cfg):
        numbers["sub-band span (m/s)"] = 2 * v_max / bands
    numbers["radar cube (KB)"] = num_range * chirps_per_frame(cfg) * num_rx * 4 / 1024
    numbers[f"CFAR matrix (KB, max {CFAR_MATRIX_MAX_BYTES // 1024})"] = num_range * folded * 2 / 1024
    return numbers
