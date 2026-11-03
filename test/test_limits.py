# SPDX-License-Identifier: MIT
"""Unit tests for the hardware-limit checks: one violation per limit, and the shipped profiles pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from ddm.cfg import parse_cfg
from ddm.limits import check

DATA = Path(__file__).parent / "data"
POINTS = (DATA / "points.cfg").read_text()
HEATMAP = (DATA / "heatmap.cfg").read_text()


@pytest.mark.parametrize("path", sorted(DATA.glob("*.cfg")), ids=lambda p: p.stem)
def test_fixtures_pass(path: Path) -> None:
    assert check(parse_cfg(path.read_text())) == []


@pytest.mark.parametrize(("base", "old", "new", "message"), [
    (POINTS, "ddmCfg 4", "ddmCfg 6", "must divide 64"),
    (POINTS, "ddmCfg 4", "ddmCfg 2", "exceed the 3 TX"),
    (POINTS, "ddmCfg 4", "ddmCfg 32", "at most 16"),
    (POINTS, "0 0 0 0 0 7\n", "0 0 0 0 0 5\n", "contiguous from TX0"),
    (POINTS, "0 0 0 0 0 7\n", "0 0 0 0 0 1\n", "at least 2 TX"),
    (POINTS, "frameCfg 0 3 32", "frameCfg 0 39 32", "chirps per loop"),
    (POINTS, "frameCfg 0 3 32", "frameCfg 0 3 128", "CFAR detection matrix"),
    (POINTS, "1 256 7200", "1 280 7200", "ADC sampling ends"),
    (POINTS, "frameCfg 0 3 32 0 100", "frameCfg 0 3 32 0 5", "chirps take"),
    (HEATMAP, "frameCfg 0 3 32 0 1000", "frameCfg 0 3 32 0 500", "heat map takes"),
    (POINTS, "profileCfg 0 77", "profileCfg 0 80", "outside 76-81 GHz"),
])
def test_violation_is_reported(base: str, old: str, new: str, message: str) -> None:
    assert old in base
    problems = check(parse_cfg(base.replace(old, new)))
    assert any(message in problem for problem in problems), problems
