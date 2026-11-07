# SPDX-License-Identifier: MIT
"""Unit tests for TOML profiles: rendering and the golden .cfg fixtures."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ddm.cfg import parse_cfg
from ddm.profile import Profile, derived, load, read, render

ROOT = Path(__file__).parents[1]
DATA = ROOT / "test" / "data"
FIXTURE = DATA / "aop.toml"  # TI's profile_3d_aop.cfg chirp
PROFILE = ROOT / "profiles" / "template.toml"
TI_PROFILE = DATA / "ti_style.cfg"  # hand-written, with TI's comment style; not a golden fixture


def commands(text: str) -> list[list[str]]:
    """Command lines in order, comments and blank lines skipped."""
    return [line.split() for line in text.splitlines() if line.split() and not line.startswith("%")]


def aop(**overrides: dict) -> Profile:
    profile = read(FIXTURE)
    for table, values in overrides.items():
        profile[table].update(values)
    return profile


@pytest.mark.parametrize(("fixture", "overrides"), [
    ("raw", {}),
    ("tdm", {"mimo": {"tdm": True}}),
])
def test_fixture_renders_golden_cfg(fixture: str, overrides: dict) -> None:
    text = render(aop(**overrides))
    assert commands(text) == commands((DATA / f"{fixture}.cfg").read_text())


def test_every_fixture_is_tested() -> None:
    assert {p.stem for p in DATA.glob("*.cfg")} - {TI_PROFILE.stem} == {"raw", "tdm"}


def test_load_checks_profile_and_sends_ti_cfg_unchanged(caplog: pytest.LogCaptureFixture) -> None:
    assert load(PROFILE)[0].splitlines()[-1] == "sensorStart"
    with caplog.at_level(logging.WARNING):
        text, _ = load(TI_PROFILE, allow_tdm=True)
    assert text == TI_PROFILE.read_text()
    assert not caplog.records


def test_cfg_without_ddmcfg_needs_tdm_flag() -> None:
    """A .cfg without ddmCfg would silently run TDM; it needs --tdm (allow_tdm)."""
    with pytest.raises(ValueError, match="no ddmCfg"):
        load(TI_PROFILE)


def test_ddmcfg_before_sensorstop_is_refused(tmp_path: Path) -> None:
    """sensorStop clears ddmCfg in the firmware, so a ddmCfg before it would be lost."""
    text = (DATA / "raw.cfg").read_text().replace("ddmCfg 4\n", "")
    with pytest.raises(ValueError, match="before sensorStop"):
        load(write(tmp_path, "early.cfg", "ddmCfg 4\n" + text))


def test_derived_numbers_of_ti_chirp() -> None:
    numbers = derived(load(FIXTURE)[1])
    assert numbers["chirp period (us)"] == 46
    assert numbers["v max (m/s)"] == pytest.approx(20.6, abs=0.05)
    assert numbers["velocity step (m/s)"] == pytest.approx(0.322, rel=1e-2)
    assert numbers["sub-band span (m/s)"] == pytest.approx(10.3, abs=0.05)
    assert numbers["raw frame (KB)"] == 512  # 128 chirps x 4 RX x 256 samples x 4 B
    assert numbers["raw data rate (MB/s)"] == pytest.approx(5.24, abs=0.01)  # 10 frames/s


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


@pytest.mark.parametrize(("old", "new", "message"), [
    ("[chirp]\n", "[chirp]\nidle = 7\n", "unknown key"),
    ("[chirp]\n", "[radar]\n[chirp]\n", "unknown table"),
    ("loops = 32", "", "loops"),
    ("# Chirp", 'extends = "x.toml"\n# Chirp', "unknown table \\[extends\\]"),  # no inheritance
])
def test_malformed_profile_is_rejected(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        read(write(tmp_path, "p.toml", FIXTURE.read_text().replace(old, new, 1)))


def test_extra_lines_replace_and_add_commands() -> None:
    profile = aop()
    profile["extra"]["lines"] = ["calibData 1 0 0x1F0000", "lowPower 0 1", "newCmd 1"]
    cfg = parse_cfg(render(profile))
    assert cfg["calibData"] == [["1", "0", "0x1F0000"]]
    assert cfg["lowPower"] == [["0", "1"]]
    assert render(profile).splitlines()[-2:] == ["newCmd 1", "sensorStart"]


def test_extra_must_not_start_the_sensor() -> None:
    profile = aop()
    profile["extra"]["lines"] = ["sensorStart"]
    with pytest.raises(ValueError, match="sensorStart"):
        render(profile)


def test_toml_limit_violation_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contiguous"):
        bad = FIXTURE.read_text().replace("tdm = false", "tx = [0, 2]\ntdm = false")
        load(write(tmp_path, "bad.toml", bad))


def test_cfg_limit_violation_is_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    text = (DATA / "raw.cfg").read_text().replace("frameCfg 0 3 32 0 100", "frameCfg 0 3 32 0 5")
    with caplog.at_level(logging.WARNING):
        load(write(tmp_path, "bad.cfg", text))
    assert "frame period" in caplog.text
