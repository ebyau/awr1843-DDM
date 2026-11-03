# Development

How the repository is organised, how to set up the toolchain, build, flash, test and lint, and
the conventions to follow when changing the code.

## Repository layout

```
build.sh                  build a firmware image (AOP or non-AOP)
flash.sh                  flash an image over UART with UniFlash
env.sh                    load the SDK build environment into the current shell
awr1843aop_serial.ccxml   UniFlash target configuration (AWR1843, serial connection)
sdk/                      mmWave SDK 03.06.02: modified sources tracked, the rest copied in locally
  packages/scripts/unix/setenv.sh   build environment (paths relative to this repository)
  packages/ti/demo/                 xwr18xx_mmw demo and demo utilities
  packages/ti/datapath/             processing chain (DPC and DPUs) and data interfaces
  packages/ti/board/                antenna geometry (stock)
profiles/                 radar profiles (TOML), rendered to TI .cfg text by the host tools
host/ddm/                 Python host tools: the ddm command
  cli.py                    ddm and its subcommands, logging and error handling
  profile.py                TOML profile -> TI .cfg text, derived numbers
  limits.py                 hardware-limit checks on a configuration
  cfg.py                    parse TI .cfg text; range, velocity, DDM and frame parameters
  radar.py                  serial control: send a configuration, start and stop the sensor
  frames.py                 decoder for the UART output frames (TLVs)
  dca.py                    raw ADC capture through a DCA1000EVM (uses xwr)
  dsp.py                    FFTs, DDM and TDM decoding of raw frames, independent of the firmware
  view.py                   live views: firmware heat map and raw-data view
  plotting.py               shared plot style and the range-Doppler plot with sub-bands
test/                     unit tests: C (Makefile, ddm_test.c, rfparser_test.c, stubs/) and
                          Python (test_*.py; data/ holds the .cfg each profile must render to)
images/                   figures used by the documentation
docs/                     documentation
pyproject.toml, uv.lock   Python project and locked dependencies (managed with uv)
out/                      build output (not tracked)
```

`.gitignore` tracks only the parts of `sdk/` this project changes (`ti/demo/xwr18xx/mmw`,
`ti/demo/utils`, `ti/datapath`, `ti/board` and `scripts/unix/setenv.sh`) and ignores build
products. Everything else under `sdk/` is a local copy of TI's SDK.

## Environment

Tested on Ubuntu 26.04, x86-64.

### TI tools

Install into `~/ti`:

| Tool | Version / directory |
|---|---|
| mmWave SDK | `mmwave_sdk_03_06_02_00-LTS` |
| ARM compiler (MSS) | `ti-cgt-arm_16.9.6.LTS` |
| C6000 compiler (DSS) | `ti-cgt-c6000_8.3.3` |
| SYS/BIOS | `bios_6_73_01_01` |
| XDCtools | `xdctools_3_50_08_24_core` |
| DSPLIB | `dsplib_c64Px_3_4_0_0`, `dsplib_c674x_3_4_0_0` |
| MATHLIB | `mathlib_c674x_3_1_2_1` |
| UniFlash | `uniflash_9.7.0` |

The SDK installer provides the compilers, SYS/BIOS, XDCtools and libraries. The directory
names are the ones `sdk/packages/scripts/unix/setenv.sh` expects.

### Populating `sdk/`

A fresh clone contains only the modified SDK directories. Copy the rest from the SDK install,
then restore this project's versions of the tracked files:

```sh
cp -r ~/ti/mmwave_sdk_03_06_02_00-LTS/firmware ~/ti/mmwave_sdk_03_06_02_00-LTS/packages sdk/
git checkout -- sdk
git status        # should show no changes under sdk/
```

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
make -C sdk/packages/ti/demo/xwr18xx/mmw mmwAOPDemo
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
./build.sh        # AOP image  -> out/xwr18xx_mmw_aop_demo.bin
./build.sh std    # non-AOP    -> out/xwr18xx_mmw_demo.bin
```

`build.sh`:

1. Loads the environment from `env.sh`.
2. Rebuilds the `rangeproc`, `dopplerproc` and `aoa2dproc` DPU libraries.
3. Cleans and rebuilds the demo (`mmwAOPDemo` or `mmwDemo` target in
   `sdk/packages/ti/demo/xwr18xx/mmw`). The object detection chain (`objectdetection.c`) and
   the demo utilities are compiled directly into the demo.
4. Copies the image to `out/` and prints the number of compiler warnings.

The full log is in `out/build.log`.

### Build variants

| Command | Make target | Antenna layout | AoA unit | DDM |
|---|---|---|---|---|
| `./build.sh` (`aop`) | `mmwAOPDemo` | AWR1843AOP (`XWR18XX_AOP_ANTENNA_PATTERN`) | `aoa2dproc` (`USE_2D_AOA_DPU`) | Supported |
| `./build.sh std` | `mmwDemo` | TI's standard (non-AOP) layout | `aoaproc` | Not supported; TDM only |

Use the AOP image on the AWR1843AOPEVM.

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
   ./flash.sh                                  # out/xwr18xx_mmw_aop_demo.bin on /dev/ttyUSB0
   ./flash.sh out/xwr18xx_mmw_demo.bin         # another image
   ./flash.sh out/xwr18xx_mmw_aop_demo.bin /dev/ttyUSB2   # another port
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
| `/dev/ttyUSB1` | Output data (TLV frames) | 921600 |

All host tools take `--cli` and `--data` to use other ports.

## Host tools

All tools are subcommands of `ddm`. A `PROFILE` is a TOML profile from `profiles/` or a TI `.cfg`
file (see [profiles](configuration.md#profiles)); `ddm COMMAND --help` lists the options.

```sh
uv run ddm cfg profiles/points.toml                 # check, show derived numbers, print the .cfg
uv run ddm points profiles/points.toml --frames 20
uv run ddm heatmap profiles/heatmap.toml
uv run ddm bands profiles/heatmap.toml --frames 5
```

| Command | Does | Options |
|---|---|---|
| `ddm cfg PROFILE` | Checks the profile against the [hardware limits](configuration.md#profiles), logs the derived numbers (chirp period, frame rate, range and velocity resolution, sub-band span, radar cube and CFAR matrix size) and prints the `.cfg` text. | `-o FILE` to write the `.cfg` to a file |
| `ddm points PROFILE` | Sends the configuration, then prints per frame: frame number, point count, nearest point's (x, y, z) in m and radial velocity in m/s. Sends `sensorStop` on exit. | `--frames N` (default 10) |
| `ddm heatmap PROFILE` | Live range-Doppler heat map (TLV type 5), Doppler axis shifted by half a sub-band so static targets sit mid-band, sub-band boundaries marked. Needs a profile with the range-Doppler heat map enabled. Close the window to stop. | `--bands N` (default from `ddmCfg`; `0` for no markers), `--snapshot FILE.png` to save one frame and exit |
| `ddm bands PROFILE` | Prints the peak level of each sub-band at the strongest range bin, relative to the strongest sub-band. With DDM working, the TX sub-bands are within a few dB and the empty one is tens of dB lower. | `--bands N` (default from `ddmCfg`), `--frames N` |

Every command takes `-v` (debug messages, including each CLI command sent, and tracebacks) or
`-q` (warnings and errors only); the hardware commands take `--cli PORT` and, where they read
the data port, `--data PORT`. Status messages go to stderr and results to stdout. An error
prints one line and exits with status 1.

For a snapshot on a machine without a display, select a non-interactive matplotlib backend:

```sh
MPLBACKEND=Agg uv run ddm heatmap profiles/heatmap.toml --snapshot map.png
```

Frames that arrive corrupted (dropped UART bytes) are skipped with a warning.

The sub-band and TX counts are read from the configuration (`ddmCfg` and the TX mask of
`chirpCfg`), and range and velocity from `profileCfg` and `frameCfg`, so the tools follow a
changed chirp configuration without extra options. `ddm decode` reads the configuration
saved in the capture file.

### Raw data capture

With the radar mounted on a [DCA1000EVM](https://www.ti.com/tool/DCA1000EVM) capture card,
the ADC samples of every chirp can be recorded while the firmware keeps processing them as usual.
`ddm capture` configures the radar and records frames with the capture card driver from
[xwr](https://github.com/RadarML/xwr); `ddm decode` decodes them in Python.

```sh
uv run ddm capture profiles/raw.toml -n 20      # -> captures/YYYYmmdd-HHMMSS_raw.npz
uv run ddm decode captures/*_raw.npz --snapshot raw-map.png
uv run ddm live profiles/raw.toml --remove-static
```

| Command | Does | Options |
|---|---|---|
| `ddm capture PROFILE` | Starts the capture card, sends the configuration, and saves complete frames as complex samples `[frame, chirp, rx, sample]` together with the configuration text. The configuration needs complex ADC output and `lvdsStreamCfg -1 0 1 0` (`raw_lvds = true` in a profile). | `-n N` (default 50), `-o FILE.npz` (default `captures/YYYYmmdd-HHMMSS_<profile>.npz`), `--cli PORT` |
| `ddm live PROFILE` | Live three-panel view: the raw range-Doppler map (with DDM, one copy per TX), the range-velocity map of the detected cells (15 dB above noise; with DDM after separating the copies, full unambiguous velocity), and a top view from the 3-TX virtual array. Brightness follows the xwr demo (amplitude^0.5, percentile-clipped). Close the window to stop the radar and capture card. | `--remove-static` (removes every TX copy of stationary objects), `--cli PORT` |
| `ddm decode CAPTURE.npz` | Range and Doppler FFTs (Hann windows), frame-averaged range-Doppler map, and the strongest targets beyond the near edge of the CFAR range window (`cfarFovCfg`) with range and velocity. With DDM, targets are found on the folded map and also listed with their TX0 sub-band, the level of every sub-band, and the weakest TX copy relative to the mean of the spare sub-bands. | `--snapshot FILE.png` |

DDM or TDM is read from the configuration: without `ddmCfg` the frame is TDM, with chirps
ordered TX0, TX1, TX2 in every loop. A TDM frame gets a Doppler FFT over the loops for each TX,
and its virtual array is corrected for the target's motion between the TX chirps
(exp(−j2π·k·m / (N_TX·N_loops)) for TX *m* at signed Doppler bin *k*).

Capture card setup (static IP `192.168.33.30` on the Ethernet port, a larger
`net.core.rmem_max`, switch settings) is described in xwr's
[setup guide](https://radarml.github.io/xwr/setup/). Keep the capture card powered off while
flashing the radar.

## Tests

```sh
make -C test       # firmware math and parser (C)
uv run pytest      # host tools (Python)
```

`make -C test` builds two host programs with `gcc` and runs them. `ddm_test` needs only
`dpif_ddm.h`; `rfparser_test` also needs SDK headers from `ti/common`, `ti/control` and
`ti/utils`, so populate `sdk/` first.

| Test | What it checks |
|---|---|
| `ddm_test` | Simulates 3 TX × 4 RX DDM chirps (firmware phase codes including the IF phase sign, Hann window, noise) for every Doppler bin from −64 to 63, on and 0.3 bin off the grid, with random antenna phases. Runs `dpif_ddm.h` (fold, empty band, TX mapping) and checks that velocity is recovered within one bin and that the virtual-array phases match the simulated antennas within 5°. |
| `test_dsp.py` (pytest) | Raw capture decoding: frame shape from a profile and rejection of unsupported streams, the capture card's I/Q byte order, range and velocity resolution, simulated 3-TX DDM targets at positive, negative and band-edge velocities resolved to the right range and signed Doppler bin, static removal, the DDM virtual array, and TDM frames: Doppler per TX, motion compensation of the virtual array, and the live-view maps. |
| `test_frames.py` (pytest) | UART frame decoding: points and other TLVs, corrupted lengths, a frame that swallows the next one (and recovery on the following frame), truncated input; `.cfg` parsing and `range_axis()`. |
| `test_profile.py` (pytest) | Each `profiles/*.toml` renders to the commands of its `test/data/*.cfg` fixture; `extends`, `[extra]` lines, rejected typos, the automatic Doppler window, and TOML errors versus `.cfg` warnings. |
| `test_limits.py` (pytest) | Every fixture passes the hardware-limit checks, and each limit reports a violation. |
| `rfparser_test` | Compiles TI's `mmwdemo_rfparser.c` with stubbed mmWave control calls and checks the parsed antenna layout or error code for: stock TDM (masks 1, 2, 4), DDM with 4 bands, DDM with 3 bands (rejected), TX0+TX2 only (rejected), and chirps with different TX masks (rejected). |

Expected output:

```
384 cases: 0 disambiguation failures, 5 off by one bin; worst virtual-array phase error 0.50 deg
PASS stock TDM 1,2,4              ret=     0 cubeTx=3 ddmNumTx=0 dopplerChirps=32
PASS DDM all-TX, 4 bands          ret=     0 cubeTx=1 ddmNumTx=3 dopplerChirps=128
...
```

The off-by-one cases are off-grid targets; see the limitations in the [README](../README.md#limitations).
`make -C test clean` removes the binaries.

The firmware itself has no automated on-target tests. To check a change on hardware, run
`ddm bands` (sub-band separation) and compare `ddm points` output with the same
scene measured in TDM with `profiles/tdm.toml` (see
[configuration.md](configuration.md#worked-example-converting-a-tdm-profile)).

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

- C99, in the style of the surrounding TI code: `Module_functionName` naming (`MmwDemo_`,
  `DPC_ObjDet_`, `AoAProcHWA_`, `DPIF_ddm`), `g` prefix for globals, TI's file layout.
- MISRA-C:2012 style: fixed-width integer types, `U` suffix on unsigned constants, no dynamic
  allocation (buffers come from the DPC memory pools), every return value checked, explicit
  casts.
- A Doxygen comment block on every function and new structure field, in TI's format
  (`@b Description`, `@n`, `@param[in]`, `@retval`).
- Keep changes minimal and inside the existing demo: add a DDM branch next to the TDM code
  rather than a parallel code path, and keep TDM behaviour bit-identical when `ddmCfg` is 0.
- No new compiler warnings: `build.sh` prints the count.
- Put hardware-independent math in `ti/datapath/dpif/dpif_ddm.h` so it can be unit-tested on
  the host. Host test code is built with `-Wall -Wextra -Werror`.

Host tools (Python): type hints, `from __future__ import annotations`, standard-library
`argparse`, `dataclasses`, `logging` and `tomllib` (no other frameworks), logging rather than
`print` for status messages in library modules, and a clean `ruff check`.

## Extending the firmware

- **New CLI command.** Add a handler and a table entry in `MmwDemo_CLIInit()`
  (`mmw_cli.c`), store the value in `MmwDemo_MSS_MCB` (`mmw_mss.h`), and decide whether
  `sensorStop` should clear it (as for `ddmCfg`). Pass it to the DSS through the
  `DPC_ObjectDetection_StaticCfg` fields filled in `MmwDemo_dataPathConfig()` (`mss_main.c`).
- **Different number of sub-bands or TX.** The sub-band arithmetic is in `dpif_ddm.h`; the
  phase codes are in `MmwDemo_ddmPhaseShift()` (`mss_main.c`). Extend `test/ddm_test.c` (its
  `NUM_TX`, `NUM_BANDS` and `NUM_CHIRPS` constants) before testing on hardware.
- **Another device.** Check the sign of the phase shift in the IF signal on that device; the
  AWR1843AOP inverts it (see `MmwDemo_ddmPhaseShift()` and `txPhase()` in `test/ddm_test.c`).
- **DSP memory.** The DSS L2 RAM is almost fully allocated: the DPC heap
  (`MMWDEMO_OBJDET_L2RAM_SIZE` in `dss/dss_main.c`, 48 KB) leaves about 1 KB of
  `L2SRAM_UMAP0` free. DSS code that outgrows it fails to link with `program will not fit into
  available memory`; the `MEMORY CONFIGURATION` table in
  `sdk/packages/ti/demo/xwr18xx/mmw/xwr18xx_mmw_aop_demo_dss.map` shows the margin. Assert
  messages embed source paths, so the margin also shrinks with a longer checkout path. Before
  shrinking the heap, check the `localRam(L2)` line of the heap statistics that `sensorStart`
  prints, for every configuration you need to support.
- **New host tool.** Add a subcommand in `host/ddm/cli.py`, reuse `radar.py`, `frames.py` and
  `dsp.py`, log with `logging.getLogger(__name__)`, add dependencies with `uv add`, and run
  `uv run ruff check` and `uv run pytest`.
- **New profile.** Add a TOML file to `profiles/` that `extends` one of the shipped profiles,
  check it with `ddm cfg`, and follow the rules in [configuration.md](configuration.md).
