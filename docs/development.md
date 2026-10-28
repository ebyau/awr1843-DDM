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
host/                     Python host tools
  mmw_host.py               send a .cfg file, print a per-frame point-cloud summary
  rd_view.py                live range-Doppler heat map with sub-band markers
  ddm_check.py              level per Doppler sub-band at the strongest range bin
  raw_capture.py            raw ADC capture through a DCA1000EVM (uses xwr)
  ddm_raw.py                DDM decoding of raw captures, independent of the firmware
  profiles/                 DDM configuration files
test/                     host unit tests in C (Makefile, ddm_test.c, rfparser_test.c, stubs/)
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
path is set in `flash.sh` (`${HOME}/ti/uniflash_9.7.0`).

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

Install [uv](https://docs.astral.sh/uv/). The host tools need Python ≥ 3.10, numpy, matplotlib
and pyserial; `ruff` is a development dependency. Create the environment from `uv.lock`:

```sh
uv sync
```

Always run the tools through `uv run`, which also syncs the environment if needed.

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

```sh
uv run python host/mmw_host.py host/profiles/ddm_aop.cfg --frames 20
uv run python host/rd_view.py host/profiles/ddm_aop_rdmap.cfg
uv run python host/ddm_check.py host/profiles/ddm_aop_rdmap.cfg --frames 5
```

| Tool | Does | Options |
|---|---|---|
| `mmw_host.py` | Sends the configuration, then prints per frame: frame number, point count, nearest point's (x, y, z) in m and radial velocity in m/s. Sends `sensorStop` on exit. Also the frame decoder used by the other tools. | `--frames N` (default 10) |
| `rd_view.py` | Live range-Doppler heat map (TLV type 5), Doppler axis shifted by half a sub-band so static targets sit mid-band, sub-band boundaries marked. Needs a profile with the range-Doppler heat map enabled. Close the window to stop. | `--bands N` (default 4, `0` for no markers), `--snapshot FILE.png` to save one frame and exit |
| `ddm_check.py` | Prints the peak level of each sub-band at the strongest range bin, relative to the strongest sub-band. With DDM working, the TX sub-bands are within a few dB and the empty one is tens of dB lower. | `--bands N`, `--frames N`, `--range-bins N` (default 256; use 128 with `ddm_phase2_aop.cfg`) |

For a snapshot on a machine without a display, select a non-interactive matplotlib backend:

```sh
MPLBACKEND=Agg uv run python host/rd_view.py host/profiles/ddm_aop_rdmap.cfg --snapshot map.png
```

Frames that arrive corrupted (dropped UART bytes) are skipped with a message on stderr by
`mmw_host.py` and `rd_view.py`.

### Raw data capture

With the radar mounted on a [DCA1000EVM](https://www.ti.com/tool/DCA1000EVM) capture card,
the ADC samples of every chirp can be recorded while the firmware keeps processing them as usual.
`raw_capture.py` configures the radar from a `.cfg` file and records frames with the capture
card driver from [xwr](https://github.com/RadarML/xwr); `ddm_raw.py` decodes them in Python.

```sh
uv run python host/raw_capture.py host/profiles/ddm_aop_raw.cfg --frames 20 --out capture.npz
uv run python host/ddm_raw.py capture.npz --snapshot raw-map.png
```

| Tool | Does | Options |
|---|---|---|
| `raw_capture.py` | Starts the capture card, sends the configuration, and saves complete frames as complex samples `[frame, chirp, rx, sample]` together with the configuration text. The configuration needs complex ADC output and `lvdsStreamCfg -1 0 1 0`; `ddm_aop_raw.cfg` is `ddm_aop.cfg` with these set and only the point cloud on the UART data port. | `--frames N` (default 50), `--out FILE.npz`, `--cli PORT` |
| `ddm_raw.py` | Range and Doppler FFTs (Hann windows), frame-averaged range-Doppler map with sub-band markers, and for the strongest targets on the folded map beyond 0.25 m: range, unambiguous velocity, TX0 sub-band, level of every sub-band, and the weakest TX copy relative to the mean of the spare sub-bands. | `--bands N` (default 4), `--tx N` (default 3), `--snapshot FILE.png` |

Capture card setup (static IP `192.168.33.30` on the Ethernet port, a larger
`net.core.rmem_max`, switch settings) is described in xwr's
[setup guide](https://radarml.github.io/xwr/setup/). Keep the capture card powered off while
flashing the radar.

## Tests

```sh
make -C test       # firmware math and parser (C)
uv run pytest      # host frame and raw-capture decoding (Python)
```

`make -C test` builds two host programs with `gcc` and runs them. `ddm_test` needs only
`dpif_ddm.h`; `rfparser_test` also needs SDK headers from `ti/common`, `ti/control` and
`ti/utils`, so populate `sdk/` first.

| Test | What it checks |
|---|---|
| `ddm_test` | Simulates 3 TX × 4 RX DDM chirps (firmware phase codes including the IF phase sign, Hann window, noise) for every Doppler bin from −64 to 63, on and 0.3 bin off the grid, with random antenna phases. Runs `dpif_ddm.h` (fold, empty band, TX mapping) and checks that velocity is recovered within one bin and that the virtual-array phases match the simulated antennas within 5°. |
| `test_ddm_raw.py` (pytest) | Raw capture decoding: frame shape from a profile and rejection of unsupported streams, the capture card's I/Q byte order, range and velocity resolution, and simulated 3-TX DDM targets at positive, negative and band-edge velocities resolved to the right range and signed Doppler bin. |
| `test_mmw_host.py` (pytest) | Frame decoding in `host/mmw_host.py`: points and other TLVs, corrupted lengths, a frame that swallows the next one (and recovery on the following frame), truncated input, and `range_axis()`. |
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
`host/ddm_check.py` (sub-band separation) and compare `host/mmw_host.py` output with the same
scene measured in TDM (see [configuration.md](configuration.md#worked-example-converting-a-tdm-profile)).

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
`argparse`, and a clean `ruff check`.

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
- **New host tool.** Put it in `host/`, reuse `send_config()` and `read_frame()` from
  `mmw_host.py`, add dependencies with `uv add`, and run `uv run ruff check`.
- **New profile.** Start from `host/profiles/ddm_aop.cfg` and follow the rules in
  [configuration.md](configuration.md).
