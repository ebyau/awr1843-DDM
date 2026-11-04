# SPDX-License-Identifier: MIT
"""Unit tests for the hardware-limit checks: one violation per limit, and the shipped profiles pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from ddm.cfg import parse_cfg
from ddm.limits import check

DATA = Path(__file__).parent / "data"
RAW = (DATA / "raw.cfg").read_text()


@pytest.mark.parametrize("path", sorted(DATA.glob("*.cfg")), ids=lambda p: p.stem)
def test_fixtures_pass(path: Path) -> None:
    assert check(parse_cfg(path.read_text())) == []


@pytest.mark.parametrize(("base", "old", "new", "message"), [
    (RAW, "ddmCfg 4", "ddmCfg 6", "must divide 64"),
    (RAW, "ddmCfg 4", "ddmCfg 2", "exceed the 3 TX"),
    (RAW, "ddmCfg 4", "ddmCfg 32", "at most 16"),
    (RAW, "0 0 0 0 0 7\n", "0 0 0 0 0 5\n", "contiguous from TX0"),
    (RAW, "0 0 0 0 0 7\n", "0 0 0 0 0 1\n", "at least 2 TX"),
    (RAW, "frameCfg 0 3 32", "frameCfg 0 39 32", "chirps per loop"),
    (RAW, "frameCfg 0 3 32", "frameCfg 0 2 32", "DDM needs 4 chirps per loop"),
    (RAW, "1 256 7200", "1 280 7200", "ADC sampling ends"),
    (RAW, "frameCfg 0 3 32 0 100", "frameCfg 0 3 32 0 5", "chirps take"),
    (RAW, "frameCfg 0 3 32 0 100", "frameCfg 0 3 32 0 6", "blank time"),  # 5.89 ms burst + 0.3 ms
    (RAW, "frameCfg 0 3 32", "frameCfg 0 3 256", "1 to 255"),
    (RAW, "frameCfg 0 3 32", "frameCfg 0 3 0", "1 to 255"),
    (RAW, "1 256 7200", "1 1025 7200", "ADC buffer"),
    (RAW.replace("channelCfg 15", "channelCfg 7"), "1 256 7200", "1 1365 7200", "ADC buffer"),  # 16 B pad
    (RAW, "chirpCfg 3 3 0 0 0 0 0 7\n", "chirpCfg 3 3 0 0 0 0 0 3\n", "same TX mask"),
    (RAW, "profileCfg 0 77 7 3 39 0 0 100", "profileCfg 0 77 7 3 39 0 0 -100", "outside 76-81 GHz"),
    (RAW, "profileCfg 0 77 7 ", "profileCfg 0 77 5243 ", "idle_us = 5243 us; at most 5242.87 us"),
    (RAW, "3 39 0 0 100", "3 5001 0 0 0.1", "ramp_end_us = 5001 us; at most 5000 us"),
    (RAW, "profileCfg 0 77", "profileCfg 0 80", "outside 76-81 GHz"),
])
def test_violation_is_reported(base: str, old: str, new: str, message: str) -> None:
    assert old in base
    problems = check(parse_cfg(base.replace(old, new)))
    assert any(message in problem for problem in problems), problems


def test_maxima_are_allowed() -> None:
    text = RAW.replace("profileCfg 0 77 7 3 39 0 0 100", "profileCfg 0 77 5242.87 3 39 0 0 100")
    text = text.replace("frameCfg 0 3 32 0 100", "frameCfg 0 3 1 0 25000")
    assert check(parse_cfg(text)) == []
    assert check(parse_cfg(RAW.replace("frameCfg 0 3 32 0 100", "frameCfg 0 3 32 0 6.2"))) == []
    assert check(parse_cfg(RAW.replace("frameCfg 0 3 32 0 100", "frameCfg 0 3 255 0 100"))) == []


def test_negative_slope_within_band_is_allowed() -> None:
    text = RAW.replace("profileCfg 0 77 7 3 39 0 0 100", "profileCfg 0 81 7 3 39 0 0 -100")
    assert check(parse_cfg(text)) == []
