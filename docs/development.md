# Development

How the repository is organised, how to set up the toolchain, build, flash, test and lint, and
the conventions to follow when changing the code.

## Repository layout

```
build.sh                  build the firmware image
flash.sh                  flash an image over UART with UniFlash
env.sh                    load the SDK build environment into the current shell
awr1843aop_serial.ccxml   UniFlash target configuration (AWR1843, serial connection)
sdk/                      mmWave SDK 03.06.02: modified sources tracked, the rest copied in locally
  packages/scripts/unix/setenv.sh   build environment (paths relative to this repository)
  packages/ti/demo/                 xwr18xx_mmw firmware (MSS only) and demo utilities
profiles/                 radar profiles (TOML), rendered to TI .cfg text by the host tools
host/ddm/                 Python host tools: the ddm command
  cli.py                    ddm and its subcommands, logging and error handling
  profile.py                TOML profile -> TI .cfg text, derived numbers
  limits.py                 hardware-limit checks on a configuration
  cfg.py                    parse TI .cfg text; range, velocity, DDM and frame parameters
  radar.py                  serial control: send a configuration, start and stop the sensor
  dca.py                    raw ADC capture through a DCA1000EVM (uses xwr)
  rawdata.py                capture byte order, lossless int16 storage, loading, plain spectrum
  view.py                   raw-signal plot: live, replayed or saved
test/                     unit tests: C (Makefile, rfparser_test.c, stubs/) and
                          Python (test_*.py; data/ holds the .cfg each profile must render to)
docs/                     documentation
pyproject.toml, uv.lock   Python project and locked dependencies (managed with uv)
out/                      build output (not tracked)
```

`.gitignore` tracks only the parts of `sdk/` this project changes (`ti/demo/xwr18xx/mmw`,
`ti/demo/utils` and `scripts/unix/setenv.sh`) and ignores build
products. Everything else under `sdk/` is a local copy of TI's SDK.

## Environment

Tested on Ubuntu 26.04, x86-64.

### TI tools

Install into `~/ti`:

| Tool | Version / directory |
|---|---|
| mmWave SDK | `mmwave_sdk_03_06_02_00-LTS` |
| ARM compiler (MSS) | `ti-cgt-arm_16.9.6.LTS` |
| SYS/BIOS | `bios_6_73_01_01` |
| XDCtools | `xdctools_3_50_08_24_core` |
| UniFlash | `uniflash_9.7.0` |

The SDK installer provides the compiler, SYS/BIOS and XDCtools. The directory names are the
ones `sdk/packages/scripts/unix/setenv.sh` expects. The installer also adds the C6000 DSP
compiler, DSPLIB and MATHLIB; the build does not use them, because the firmware has no DSP
program.

### Populating `sdk/`

A fresh clone contains only the modified SDK directories. Copy the rest from the SDK install,
then restore this project's versions of the tracked files:

```sh
cp -r ~/ti/mmwave_sdk_03_06_02_00-LTS/firmware ~/ti/mmwave_sdk_03_06_02_00-LTS/packages sdk/
git checkout -- sdk
git status        # should show no changes under sdk/
```

The copy also brings back parts of TI's demo that this firmware removes (`mmw/dss/`,
`mmw/docs/`, `mmw/profiles/`, `mmw/include/mmw_output.h`); `.gitignore` ignores them and the
build does not use them.

The build needs `sdk/firmware/radarss/` (radar subsystem firmware packed into the image) and
the SDK's drivers, control, utils and build scripts under `sdk/packages/`.

### Build environment

`sdk/packages/scripts/unix/setenv.sh` is TI's script with four settings changed:

| Variable | Value | Effect |
|---|---|---|
| `MMWAVE_SDK_DEVICE` | `awr18xx` | Target device |
| `DOWNLOAD_FROM_CCS` | `no` | Images are built for flashing, not for loading from Code Composer Studio |
| `MMWAVE_SDK_TOOLS_INSTALL_PATH` | `${MMWAVE_SDK_TOOLS_INSTALL_PATH:-${HOME}/ti}` | Tool location; override by exporting the variable |
| `MMWAVE_SDK_INSTALL_PATH` | `sdk/packages` of this repository, computed from the script's location | The build uses the repository's SDK copy, not the one in `~/ti` |

If the TI tools are elsewhere, export `MMWAVE_SDK_TOOLS_INSTALL_PATH` before building. UniFlash's
path defaults to `${HOME}/ti/uniflash_9.7.0`; set `UNIFLASH_DIR` to use another install.

`env.sh` sources `setenv.sh` into the current shell. `build.sh` does this itself; source it
only for running `make` by hand:

```sh
source env.sh
make -C sdk/packages/ti/demo/xwr18xx/mmw mmwDemo
```

### System packages and permissions

```sh
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install libc6:i386 libstdc++6:i386 make mono-runtime gcc
sudo usermod -aG dialout $USER     # serial port access; log out and back in
```

The i386 libraries and Mono are needed by TI's image-packaging tools; `gcc` builds the host
tests.

ModemManager probes new USB serial devices and interferes with flashing. Tell it to ignore the
board's Silicon Labs CP2105 bridge (USB ID `10c4:ea70`):

```sh
echo 'ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea70", ENV{ID_MM_DEVICE_IGNORE}="1"' \
  | sudo tee /etc/udev/rules.d/71-mm-ignore-cp2105.rules
sudo udevadm control --reload-rules
```

### Python

Install [uv](https://docs.astral.sh/uv/). The host tools need Python ≥ 3.11, numpy, matplotlib,
pyserial and xwr; `pytest` and `ruff` are development dependencies. Create the environment from `uv.lock`:

```sh
uv sync
```

This installs the host tools as the `ddm` command in the project environment. Always run it
through `uv run`, which also syncs the environment if needed.

## Building

```sh
./build.sh        # -> out/xwr18xx_mmw_demo.bin
```

`build.sh`:

1. Loads the environment from `env.sh`.
2. Cleans and rebuilds the firmware (`mmwDemo` target in `sdk/packages/ti/demo/xwr18xx/mmw`).
   The demo utilities (RF parser, ADC buffer configuration, flash access) are compiled
   directly into it.
3. Copies the image to `out/` and prints the number of compiler warnings.

The full log is in `out/build.log`. The image holds the MSS program and TI's radar subsystem
firmware only; there is no DSP program. The same image runs on the AWR1843AOPEVM; the antenna
layout matters only to processing on the PC.

## Flashing

The board is flashed over its command UART. The SOP (sense-on-power) switches select the boot
mode, which is read only at power-up:

| Mode | SOP0 | SOP1 | SOP2 |
|---|---|---|---|
| Flashing | on | off | on |
| Normal (run firmware) | on | off | off |

1. Set flashing mode, then unplug and replug the USB cable.
2. Run the script:

   ```sh
   ./flash.sh                                  # out/xwr18xx_mmw_demo.bin on /dev/ttyUSB0
   ./flash.sh other.bin                        # another image
   ./flash.sh out/xwr18xx_mmw_demo.bin /dev/ttyUSB2   # another port
   ```

   It runs UniFlash's `dslite.sh` with `awr1843aop_serial.ccxml` and prints only lines that
   contain `SUCCESS`, `error:` or `Failed`.
3. Set normal mode, then unplug and replug the USB cable.

### Troubleshooting

- **Second attempt fails.** The bootloader accepts one flashing session per power-up.
  Replug the USB cable before every attempt.
- **Switch change has no effect.** The SOP mode latches at power-up; replug after changing
  the switches.
- **Port busy or connection fails right after plugging in.** Check that the ModemManager
  udev rule above is installed.
- **Permission denied on `/dev/ttyUSB*`.** Add yourself to `dialout` and log in again.
- **Wrong port.** The board creates two ports; with other USB serial adapters connected the
  numbers may shift. `ls -l /dev/serial/by-id/` shows which is which. Flash on the first
  (command) port.

## Serial ports

| Port | Use | Baud |
|---|---|---|
| `/dev/ttyUSB0` | CLI commands and flashing | 115200 |
| `/dev/ttyUSB1` | Unused: the firmware sends no data on the UART | |

The radar's data goes over LVDS to the DCA1000EVM, which forwards it to the PC over Ethernet.
The hardware commands take `--cli` to use another port.

## Host tools

All tools are subcommands of `ddm`. A `PROFILE` is a TOML profile from `profiles/` or a TI `.cfg`
file (see [profiles](configuration.md#profiles)); `ddm COMMAND --help` lists the options.

```sh
uv run ddm cfg profiles/template.toml    # check, show derived numbers, print the .cfg
```

| Command | Does | Options |
|---|---|---|
| `ddm cfg PROFILE` | Checks the profile against the [hardware limits](configuration.md#limits), logs the derived numbers (chirp period and burst, frame rate, range and velocity resolution, sub-band span, raw frame size and data rate) and prints the `.cfg` text. | `-o FILE` to write the `.cfg` to a file |

Every command takes `-v` (debug messages, including each CLI command sent, and tracebacks) or
`-q` (warnings and errors only). Status messages go to stderr and results to stdout. An error
prints one line and exits with status 1.

The sub-band and TX counts are read from the configuration (`ddmCfg` and the TX mask of
`chirpCfg`), and range and velocity from `profileCfg` and `frameCfg`, so the tools follow a
changed chirp configuration without extra options. `ddm show` reads the configuration
saved in the capture file.

### Raw data capture

With the radar mounted on a [DCA1000EVM](https://www.ti.com/tool/DCA1000EVM) capture card,
the ADC samples of every chirp are recorded on the PC.
`ddm capture` configures the radar and records frames with the capture card driver from
[xwr](https://github.com/RadarML/xwr). Nothing is processed on the way: the PC stores and
plots the samples as the radar produced them.

```sh
uv run ddm capture profiles/template.toml -n 20   # -> captures/YYYYmmdd-HHMMSS_template.npz
uv run ddm live profiles/template.toml           # raw spectrum, live
uv run ddm show captures/*_template.npz           # the same plot for a capture
```

| Command | Does | Options |
|---|---|---|
| `ddm capture PROFILE` | Starts the capture card, sends the configuration, and saves every frame unchanged (format below). A `.cfg` file needs complex ADC output, `adcbufCfg -1 0 1 1 1` and `lvdsStreamCfg -1 0 1 0`, and `--tdm` if it has no `ddmCfg`. | `-n N` (default 50), `-o FILE.npz` (default `captures/YYYYmmdd-HHMMSS_<profile>.npz`), `--cli PORT`, `--tdm` |
| `ddm live PROFILE` | Live range-Doppler spectrum of RX 0, with no processing besides the FFTs (no window, static removal or detection), as 20·log10\|FFT\| in dB re 1 ADC count on a scale fixed by the first frame. Zero Doppler is centred; with DDM, TX *k*'s copy sits *k* sub-bands up. Close the window to stop the radar and capture card. | `--cli PORT`, `--tdm` |
| `ddm show CAPTURE.npz` | The same plot for a saved capture, replayed in a loop at the frame period. Lists incomplete frames. Older captures also load. | `--snapshot FILE.png` (save the first frame instead) |

DDM or TDM is read from the configuration: without `ddmCfg` the frame is TDM, with chirps
ordered TX0, TX1, TX2 in every loop. The mode is printed and shown in the plot title.

A capture (`.npz`, format 2, read with `ddm.rawdata.load_capture`) holds:

| Key | Contents |
|---|---|
| `iq` | int16 `[frame, chirp, rx, sample, 2]` (I, Q), unprocessed |
| `config` | the `.cfg` text the radar ran |
| `complete` | bool per frame; `False` where the capture card lost data: the contents are unreliable (partly zero-filled). No frame is left out after the first one received, so frame *k* started *k* frame periods after frame 0 |
| `timestamp` | float per frame: PC clock (Unix s) when the host read the frame's first data. Approximate (network and OS delays); use frame index × frame period for timing, and the timestamp to spot stalls |
| `meta` | JSON: `format`, `mode` (`ddm`/`tdm`), `frames`, `incomplete`, `start_time`, `host` version, git `commit` |

Format 1 captures (`iq` and `config` only) and older complex64 `frames` captures load as complete
frames with unknown times. They left out incomplete frames, so their frames are not guaranteed
to be evenly spaced in time.

Capture card setup (static IP `192.168.33.30` on the Ethernet port, a larger
`net.core.rmem_max`, switch settings) is described in xwr's
[setup guide](https://radarml.github.io/xwr/setup/). Keep the capture card powered off while
flashing the radar.

## Tests

```sh
make -C test       # RF parser with the DDM chirp checks (C)
uv run pytest      # host tools (Python)
```

`make -C test` builds `rfparser_test` with `gcc` and runs it. It needs SDK headers from
`ti/common`, `ti/control` and `ti/utils`, so populate `sdk/` first; it is run by hand.
GitHub Actions (`.github/workflows/ci.yml`) runs `ruff` and `pytest` on every push.

| Test | What it checks |
|---|---|
| `test_rawdata.py` (pytest) | Frame shape from a profile and rejection of unsupported streams, the capture card's I/Q byte order, bit-exact int16 capture storage (and loading of older captures), the unwindowed spectrum, spectrum axes that place a simulated target at its true range and velocity, the `ddm show` plot of a capture, capture metadata, and one frame recorded on the board (`test/data/still_ddm.npz`, a still object at 1.4 m) whose TX copies land at Doppler 0, +32 and −64 with the empty band over 30 dB below. |
| `test_cfg.py` (pytest) | `.cfg` parsing, `ddm_params()` and `range_axis()`. |
| `test_profile.py` (pytest) | `test/data/aop.toml` (the chirp of TI's `profile_3d_aop.cfg`), with DDM and with TDM, gives the commands of its `test/data/*.cfg` fixture in order; `profiles/template.toml` loads and passes the limits; a TI-style `.cfg` (`test/data/ti_style.cfg`) is sent unchanged with `--tdm` and refused without it; derived numbers, `[extra]` lines, rejected typos, and TOML errors versus `.cfg` warnings. |
| `test_limits.py` (pytest) | Every fixture passes the hardware-limit checks, and each limit reports a violation. |
| `rfparser_test` | Compiles TI's `mmwdemo_rfparser.c` with stubbed mmWave control calls and checks the parsed antenna layout or error code for: stock TDM (masks 1, 2, 4), DDM with 4 bands, DDM with 3 bands (rejected), TX0+TX2 only (rejected), and chirps with different TX masks (rejected). |

Expected output:

```
PASS stock TDM 1,2,4              ret=     0 cubeTx=3 ddmNumTx=0 dopplerChirps=32
PASS DDM all-TX, 4 bands          ret=     0 cubeTx=1 ddmNumTx=3 dopplerChirps=128
...
```

`make -C test clean` removes the binaries.

The firmware itself has no automated on-target tests. To check a change on hardware, run
`ddm show` on a capture of a static scene: each static object should appear once per TX, in
consecutive sub-bands, and the empty sub-band should be tens of dB below the TX copies. To compare with TDM, capture the same scene with `tdm = true`.

## Linting

```sh
uv run ruff check
```

Settings are in `pyproject.toml`: line length 110, rule sets `E`, `F`, `W`, `I`, `B`, `UP`,
`SIM`.

## Comparing with TI's SDK

The first commit contains TI's unmodified sources for the tracked SDK directories. To see
every firmware change:

```sh
git diff $(git rev-list --max-parents=0 HEAD) -- sdk
git diff --stat $(git rev-list --max-parents=0 HEAD) -- sdk    # list of changed files
```

The changed files are listed in [architecture.md](architecture.md#changed-files).

## Coding conventions

Firmware (C):

- C99, in the style of the surrounding TI code: `Module_functionName` naming (`MmwDemo_`),
  `g` prefix for globals, TI's file layout.
- MISRA-C:2012 style: fixed-width integer types, `U` suffix on unsigned constants, no dynamic
  allocation, every return value checked, explicit casts.
- A Doxygen comment block on every function and new structure field, in TI's format
  (`@b Description`, `@n`, `@param[in]`, `@retval`).
- The firmware only configures the sensor and streams raw data. Signal processing belongs in
  the host tools.
- No new compiler warnings: `build.sh` prints the count. Host test code is built with
  `-Wall -Wextra -Werror`.

Host tools (Python): type hints, `from __future__ import annotations`, standard-library
`argparse`, `dataclasses`, `logging` and `tomllib` (no other frameworks), logging rather than
`print` for status messages in library modules, and a clean `ruff check`.

## Extending the firmware

- **New CLI command.** Add a handler and a table entry in `MmwDemo_CLIInit()`
  (`mmw_cli.c`), store the value in `MmwDemo_MSS_MCB` (`mmw_mss.h`), and decide when it is
  cleared (`ddmCfg` is pending until a successful `sensorStart`).
- **Different number of sub-bands or TX.** The phase codes are in `MmwDemo_ddmPhaseShift()`
  (`mss_main.c`); the host tools read both from the configuration.
- **Another device.** Check the sign of the phase shift in the IF signal on that device; the
  AWR1843AOP inverts it (see `MmwDemo_ddmPhaseShift()`).
- **New host tool.** Add a subcommand in `host/ddm/cli.py`, reuse `radar.py`, `dca.py` and
  `rawdata.py`, log with `logging.getLogger(__name__)`, add dependencies with `uv add`, and run
  `uv run ruff check` and `uv run pytest`.
- **New profile.** Copy `profiles/template.toml`, check it with `ddm cfg`, and follow the rules in [configuration.md](configuration.md).
