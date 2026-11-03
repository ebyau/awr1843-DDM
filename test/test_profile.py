# SPDX-License-Identifier: MIT
"""Unit tests for TOML profiles: rendering, inheritance and the golden .cfg fixtures."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ddm.cfg import parse_cfg
from ddm.profile import derived, load, read, render

ROOT = Path(__file__).parents[1]
PROFILES = sorted((ROOT / "profiles").glob("*.toml"))
TI_PROFILE = ROOT / "sdk/packages/ti/demo/xwr18xx/mmw/profiles/profile_3d_aop.cfg"


def test_every_profile_has_a_fixture() -> None:
    assert {p.stem for p in PROFILES} == {p.stem for p in (ROOT / "test" / "data").glob("*.cfg")}


@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.stem)
def test_profile_renders_its_golden_fixture(path: Path) -> None:
    text, cfg = load(path)
    assert cfg == parse_cfg((ROOT / "test" / "data" / f"{path.stem}.cfg").read_text())
    assert text.splitlines()[-1] == "sensorStart"


def test_ti_profile_loads_without_warnings(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        load(TI_PROFILE)
    assert not caplog.records


def test_derived_numbers_of_points_profile() -> None:
    numbers = derived(load(ROOT / "profiles" / "points.toml")[1])
    assert numbers["chirp period (us)"] == 46
    assert numbers["v max (m/s)"] == pytest.approx(20.6, abs=0.05)
    assert numbers["velocity step (m/s)"] == pytest.approx(0.322, rel=1e-2)
    assert numbers["sub-band span (m/s)"] == pytest.approx(10.3, abs=0.05)
    assert numbers["CFAR matrix (KB, max 32)"] == 16


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_child_keys_override_parent_tables(tmp_path: Path) -> None:
    base = (ROOT / "profiles" / "points.toml").read_text()
    write(tmp_path, "base.toml", base)
    child = write(tmp_path, "child.toml", 'extends = "base.toml"\n[frame]\nloops = 16\n')
    profile = read(child)
    assert profile["frame"] == {"loops": 16, "period_ms": 100}
    assert profile["chirp"]["idle_us"] == 7


def test_only_one_level_of_extends(tmp_path: Path) -> None:
    write(tmp_path, "a.toml", (ROOT / "profiles" / "points.toml").read_text())
    write(tmp_path, "b.toml", 'extends = "a.toml"\n')
    with pytest.raises(ValueError, match="one level"):
        read(write(tmp_path, "c.toml", 'extends = "b.toml"\n'))


@pytest.mark.parametrize(("text", "message"), [
    ("[chirp]\nidle = 7\n", "unknown key"),
    ("[radar]\n", "unknown table"),
])
def test_typos_are_rejected(tmp_path: Path, text: str, message: str) -> None:
    write(tmp_path, "base.toml", (ROOT / "profiles" / "points.toml").read_text())
    with pytest.raises(ValueError, match=message):
        read(write(tmp_path, "child.toml", 'extends = "base.toml"\n' + text))


def test_missing_required_key_is_rejected(tmp_path: Path) -> None:
    text = (ROOT / "profiles" / "points.toml").read_text().replace("loops = 32\n", "")
    with pytest.raises(ValueError, match="loops"):
        read(write(tmp_path, "p.toml", text))


def test_extra_lines_replace_and_add_commands() -> None:
    profile = read(ROOT / "profiles" / "points.toml")
    profile["extra"]["lines"] = ["cfarCfg -1 0 2 8 4 3 0 12.0 0", "clutterRemoval -1 1", "newCmd 1"]
    cfg = parse_cfg(render(profile))
    assert cfg["cfarCfg"] == [["-1", "0", "2", "8", "4", "3", "0", "12.0", "0"]]
    assert cfg["clutterRemoval"] == [["-1", "1"]]
    assert render(profile).splitlines()[-2:] == ["newCmd 1", "sensorStart"]


def test_doppler_window_follows_the_chirp() -> None:
    profile = read(ROOT / "profiles" / "points.toml")
    profile["chirp"]["idle_us"] = 435
    assert parse_cfg(render(profile))["cfarFovCfg"][1] == ["-1", "1", "-2.1", "2.1"]


def test_toml_limit_violation_is_an_error(tmp_path: Path) -> None:
    write(tmp_path, "base.toml", (ROOT / "profiles" / "points.toml").read_text())
    with pytest.raises(ValueError, match="contiguous"):
        load(write(tmp_path, "bad.toml", 'extends = "base.toml"\n[mimo]\ntx = [0, 2]\n'))


def test_cfg_limit_violation_is_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    text = (ROOT / "test" / "data" / "points.cfg").read_text()
    text = text.replace("frameCfg 0 3 32 0 100", "frameCfg 0 3 32 0 5")
    with caplog.at_level(logging.WARNING):
        load(write(tmp_path, "bad.cfg", text))
    assert "frame period" in caplog.text
