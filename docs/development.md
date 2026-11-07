# Development

## Repository layout

```
build.sh, flash.sh, env.sh   build, flash, load the SDK environment
awr1843aop_serial.ccxml      UniFlash target (AWR1843, serial)
sdk/                         mmWave SDK 03.06.02: modified files tracked, the rest copied in
  packages/scripts/unix/setenv.sh   build environment
  packages/ti/demo/                 firmware (MSS only) and demo utilities
profiles/                    TOML radar profiles
host/ddm/                    the ddm command
  cli.py      subcommands, logging, errors
  profile.py  TOML -> .cfg, derived numbers
  limits.py   hardware-limit checks
  cfg.py      .cfg parsing; range, velocity, DDM, frame parameters
  radar.py    serial control
  dca.py      capture through the DCA1000EVM (xwr)
  rawdata.py  byte order, capture files, plain spectrum, antenna layout
  view.py     raw spectrum plot: live, replayed, saved
test/                        Python tests (test_*.py, data/), C test (rfparser_test.c)
docs/                        documentation
out/                         build output (not tracked)
```

## Environment

Ubuntu x86-64. TI tools in `~/ti` (the SDK installer adds the compiler, SYS/BIOS and XDCtools):

| Tool | Directory |
|---|---|
| mmWave SDK | `mmwave_sdk_03_06_02_00-LTS` |
| ARM compiler | `ti-cgt-arm_16.9.6.LTS` |
| SYS/BIOS | `bios_6_73_01_01` |
| XDCtools | `xdctools_3_50_08_24_core` |
| UniFlash | `uniflash_9.7.0` |

### Populating `sdk/`

A clone holds only the modified SDK files. Copy the rest, then restore ours:

```sh
cp -r ~/ti/mmwave_sdk_03_06_02_00-LTS/firmware ~/ti/mmwave_sdk_03_06_02_00-LTS/packages sdk/
git checkout -- sdk
git status        # no changes under sdk/
```

Parts of TI's demo this firmware drops (`mmw/dss/`, `mmw/docs/`, `mmw/profiles/`,
`mmw/include/mmw_output.h`) come back with the copy; they are ignored and unused.

### Build environment

`sdk/packages/scripts/unix/setenv.sh` is TI's script with these changes:

| Variable | Value |
|---|---|
| `MMWAVE_SDK_DEVICE` | `awr18xx` |
| `DOWNLOAD_FROM_CCS` | `no` (images for flashing) |
| `MMWAVE_SDK_TOOLS_INSTALL_PATH` | `${MMWAVE_SDK_TOOLS_INSTALL_PATH:-${HOME}/ti}` |
| `MMWAVE_SDK_INSTALL_PATH` | this repository's `sdk/packages` |

Tools elsewhere: export `MMWAVE_SDK_TOOLS_INSTALL_PATH`. Another UniFlash: set `UNIFLASH_DIR`.
For `make` by hand: `source env.sh`, then `make -C sdk/packages/ti/demo/xwr18xx/mmw mmwDemo`.

### System packages

```sh
sudo dpkg --add-architecture i386 && sudo apt update
sudo apt install libc6:i386 libstdc++6:i386 make mono-runtime gcc   # TI packaging tools, C test
sudo usermod -aG dialout $USER                                      # serial access; log in again
echo 'ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea70", ENV{ID_MM_DEVICE_IGNORE}="1"' \
  | sudo tee /etc/udev/rules.d/71-mm-ignore-cp2105.rules           # keep ModemManager away
sudo udevadm control --reload-rules
```

### Python

[uv](https://docs.astral.sh/uv/), Python ≥ 3.11. `uv sync` installs the locked environment;
run the tools with `uv run ddm ...`.

## Building

```sh
./build.sh        # -> out/xwr18xx_mmw_demo.bin, log in out/build.log
```

Cleans and rebuilds the `mmwDemo` target and prints the warning count. The image holds the MSS
program and TI's radar subsystem firmware; no DSP program.

## Flashing

| Mode | SOP0 | SOP1 | SOP2 |
|---|---|---|---|
| Flashing | on | off | on |
| Normal | on | off | off |

Set flashing mode, replug USB, run `./flash.sh [image] [port]` (default
`out/xwr18xx_mmw_demo.bin` on `/dev/ttyUSB0`), set normal mode, replug.

- **Second attempt fails:** one flash per power-up; replug first.
- **Switches ignored:** SOP is read at power-up; replug.
- **Port busy:** install the ModemManager rule above.
- **Permission denied:** join `dialout`, log in again.
- **Wrong port:** `ls -l /dev/serial/by-id/`; flash on the first (command) port.

## Serial ports

`/dev/ttyUSB0`: CLI and flashing, 115200 baud. `/dev/ttyUSB1`: unused (data goes over LVDS).
`--cli PORT` selects another port.

## Host tools

`uv run ddm COMMAND --help` lists options. `-v` shows each CLI command and tracebacks, `-q`
only warnings. Errors print one line and exit with status 1. Mode, sub-bands, TX, range and
velocity are read from the configuration; `ddm show` uses the one saved in the capture.

### Raw data capture

Card setup (static IP `192.168.33.30`, `net.core.rmem_max`, switches): xwr's
[setup guide](https://radarml.github.io/xwr/setup/). Keep the card off while flashing.

| Command | Does | Options |
|---|---|---|
| `ddm cfg PROFILE` | Check [limits](configuration.md#limits), log derived numbers, print the `.cfg` | `-o FILE` |
| `ddm capture PROFILE` | Record every frame unchanged | `-n N` (50), `-o FILE.npz`, `--tdm` |
| `ddm live PROFILE` | Live 20·log10\|FFT\| range-Doppler of RX 0, no window, scale fixed by the first frame | `--tdm` |
| `ddm show CAPTURE.npz` | Replay at the frame period; lists incomplete frames | `--snapshot FILE.png` |

A `.cfg` file needs `adcCfg 2 1`, `adcbufCfg -1 0 1 1 1`, `lvdsStreamCfg -1 0 1 0`, and
`ddmCfg` (or `--tdm`). Profiles: [configuration.md](configuration.md#profiles).

A capture (`.npz`, format 2, `ddm.rawdata.load_capture`):

| Key | Contents |
|---|---|
| `iq` | int16 `[frame, chirp, rx, sample, 2]` (I, Q), unprocessed |
| `config` | the `.cfg` the radar ran |
| `complete` | per frame; `False`: the card lost data, contents unreliable. No frame is left out, so frame *k* started *k* periods after frame 0 |
| `timestamp` | per frame: PC time (Unix s) the frame was read; approximate, for spotting stalls |
| `meta` | JSON: `format`, `mode` (`ddm`/`tdm`), `frames`, `incomplete`, `start_time` |

Older captures (format 1, complex64) load as complete frames with unknown times; they skipped
incomplete frames, so their timing is not guaranteed.

## Tests

```sh
uv run pytest      # host tools; CI runs it with ruff on every push
make -C test       # RF parser (C); needs the populated sdk/, run by hand
```

| Test | Checks |
|---|---|
| `test_rawdata.py` | Frame shape and stream checks, I/Q byte order, capture files and metadata, older captures, unwindowed spectrum and axes, the `ddm show` plot |
| `test_cfg.py` | `.cfg` parsing, DDM parameters, range axis |
| `test_profile.py` | Profiles render to their fixtures, the template passes, `.cfg` files sent unchanged, the TDM guard, derived numbers, `[extra]`, typos |
| `test_limits.py` | Fixtures pass; each limit reports a violation |
| `rfparser_test` | TI's RF parser on TDM and DDM layouts |

On hardware: `ddm show` a still scene; each object appears once per TX in consecutive
sub-bands, and the empty sub-band is tens of dB lower.

## Linting

`uv run ruff check` (settings in `pyproject.toml`).
