# DDM-MIMO firmware for the AWR1843AOP

Firmware for the Texas Instruments AWR1843AOPEVM radar that uses Doppler-division multiplexing
(DDM) MIMO. It is based on the out-of-box demo in TI's mmWave SDK 03.06.02 (`xwr18xx_mmw`,
AOP variant) and keeps that demo's command interface and output format.

## How DDM works

A MIMO radar needs to tell apart the signals from its transmit (TX) antennas so it can form a
virtual antenna array for angle estimation.

- **TDM-MIMO** (TI's stock demo) transmits from one TX per chirp, cycling TX0 → TX1 → TX2.
- **DDM-MIMO** (this firmware) transmits from all TX on every chirp. Each TX gets a per-chirp
  phase code, so in the Doppler spectrum its copy of a target is shifted by a fixed number of
  sub-bands. With 3 TX and 4 sub-bands, TX *k* lands in sub-band *k* relative to TX0 and one
  sub-band stays empty. Finding the empty sub-band identifies which copy came from which TX,
  which also resolves the target's velocity over the full chirp rate.

Compared with TDM on the same chirp profile, each TX is on for every chirp instead of one in
three, and there is no motion phase error between TX copies. The firmware runs either mode:
`ddmCfg 0`, or no `ddmCfg` command, gives the stock TDM behaviour.

## Repository layout

```
build.sh                 build the firmware image
flash.sh                 flash an image over UART with UniFlash
env.sh                   load the SDK build environment
awr1843aop_serial.ccxml  UniFlash target configuration (serial)
sdk/                     mmWave SDK 03.06.02 packages, including the modified sources
host/                    Python tools to configure the radar and read its output
  mmw_host.py              send a .cfg file and print a per-frame point-cloud summary
  ddm_check.py             report signal level per Doppler sub-band (range-Doppler heat map)
  profiles/                example DDM configurations
test/                    host unit tests (C, built with gcc)
docs/                    design notes
```

`sdk/` is a complete copy of the SDK so the firmware builds without a separate SDK install.
Git tracks only the parts that are modified; everything else is stock TI.

## Firmware structure

The radar has two processors. The **MSS** (ARM Cortex-R4F) handles the command line and
configures the RF front end. The **DSS** (C674x DSP, with a hardware FFT accelerator) runs the
signal processing chain each frame. DDM touches both.

| Stage | Runs on | Source | DDM behaviour |
|---|---|---|---|
| Command line | MSS | `ti/demo/xwr18xx/mmw/mss/mmw_cli.c` | `ddmCfg <numBands>` sets the number of Doppler sub-bands |
| RF setup | MSS | `ti/demo/xwr18xx/mmw/mss/mss_main.c` | Enables the per-chirp TX phase shifters and programs the phase codes |
| Chirp config parsing | MSS | `ti/demo/utils/mmwdemo_rfparser.c` | Validates DDM chirps; describes the radar cube as one TX block |
| Range FFT | DSS | `ti/datapath/dpu/rangeproc` | Unchanged |
| Doppler FFT | DSS | `ti/datapath/dpc/dpu/dopplerproc` | Unchanged; produces a full-width detection matrix |
| Sub-band fold | DSS | `ti/datapath/dpc/objectdetection/objdethwa` | Averages the sub-bands into one detection matrix |
| Detection (CFAR) | DSS | `ti/datapath/dpc/dpu/cfarcaproc` | Runs on the folded matrix |
| Angle of arrival | DSS | `ti/datapath/dpc/dpu/aoa2dproc` | Per target: finds the empty sub-band, builds the virtual array, computes velocity |

The DDM-specific math (fold, empty-band search, TX-to-Doppler-bin mapping) is in
`ti/datapath/dpif/dpif_ddm.h`. These are pure C functions with no hardware dependencies, so the
DSP firmware and the host tests use the same code.

The first commit holds TI's unmodified sources. To see every change against them:

```
git diff $(git rev-list --max-parents=0 HEAD) -- sdk
```

## Prerequisites

- Ubuntu (tested on 26.04), x86-64.
- [mmWave SDK 03.06.02](https://www.ti.com/tool/MMWAVE-SDK) installed in `~/ti`, for the TI
  compilers, SYS/BIOS, XDCtools and DSP libraries.
- [UniFlash](https://www.ti.com/tool/UNIFLASH) 9.7 installed in `~/ti/uniflash_9.7.0`.
- System packages:

  ```
  sudo dpkg --add-architecture i386
  sudo apt update
  sudo apt install libc6:i386 libstdc++6:i386 make mono-runtime gcc python3-serial python3-numpy
  ```

  The i386 libraries and Mono are needed by TI's image-packaging tools.
- Serial port access: `sudo usermod -aG dialout $USER`, then log out and back in.
- Stop ModemManager from probing the board's USB-UART bridge (Silicon Labs CP2105), which
  interferes with flashing:

  ```
  echo 'ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea70", ENV{ID_MM_DEVICE_IGNORE}="1"' \
    | sudo tee /etc/udev/rules.d/71-mm-ignore-cp2105.rules
  sudo udevadm control --reload-rules
  ```

If your TI tools are not in `~/ti`, set `MMWAVE_SDK_TOOLS_INSTALL_PATH` to their location before
building, and adjust the UniFlash path in `flash.sh`.

## Build

```
./build.sh        # AOP antenna layout -> out/xwr18xx_mmw_aop_demo.bin
./build.sh std    # TI's non-AOP layout -> out/xwr18xx_mmw_demo.bin (TDM only)
```

The script rebuilds the modified signal-processing libraries and the demo, and writes the full
log to `out/build.log`. Use the AOP image for the AWR1843AOPEVM.

## Flash

The board is flashed over its UART. The boot mode is set with the SOP switches and only takes
effect at power-up:

| Mode | SOP0 | SOP1 | SOP2 |
|---|---|---|---|
| Flashing | on | off | on |
| Normal (run firmware) | on | off | off |

1. Set flashing mode, then unplug and replug the USB cable.
2. Run `./flash.sh`, or `./flash.sh <image.bin> [port]` for another image or port.
3. Set normal mode, then unplug and replug the USB cable.

The bootloader accepts one flashing session per power-up. If an attempt fails, power-cycle the
board before trying again.

## Run

The board appears as two serial ports:

| Port | Use | Baud |
|---|---|---|
| `/dev/ttyUSB0` | Commands | 115200 |
| `/dev/ttyUSB1` | Output data | 921600 |

Send a configuration and print a summary of each frame:

```
python3 host/mmw_host.py host/profiles/ddm_aop.cfg --frames 20
```

Each line shows the frame number, the number of detected points, and the nearest target's
position (m) and radial velocity (m/s). Use `--cli` and `--data` for other ports.

To check the sub-band separation directly, enable the range-Doppler heat map in the
configuration (`guiMonitor`) and run `host/ddm_check.py`. With DDM working, the sub-bands that
hold TX copies show similar levels and the empty sub-band is far lower.

## Configuring DDM

`host/profiles/ddm_aop.cfg` is a complete example. It is TI's `profile_3d_aop.cfg` with these
changes:

```
chirpCfg 0 0 0 0 0 0 0 7      # every chirp enables all 3 TX (bit mask 7)
chirpCfg 1 1 0 0 0 0 0 7
chirpCfg 2 2 0 0 0 0 0 7
chirpCfg 3 3 0 0 0 0 0 7
frameCfg 0 3 32 0 100 1 0     # one chirp per sub-band, 32 loops: 128 chirps per frame
cfarFovCfg -1 1 -21.2 21.2    # keep the Doppler field of view wide open
ddmCfg 4                      # 4 Doppler sub-bands
sensorStart
```

Rules:

- `ddmCfg` goes before `sensorStart`. `sensorStop` clears it, so each configuration that uses DDM
  must include it.
- `numBands` must divide 64 (the phase shifter has 64 steps) and be larger than the number of
  TX, up to 16.
- Every chirp in the frame enables the same TX set, starting at TX0.
- `frameCfg` has exactly `numBands` chirps per loop.
- Detection runs before velocity is resolved, so the Doppler field of view (`cfarFovCfg ... 1`)
  must cover the full range.
- These options assume one TX per chirp and are rejected at `sensorStart` when DDM is on:
  `measureRangeBiasAndRxChanPhase` (calibrate in TDM mode instead), `clutterRemoval`,
  `calibDcRangeSig` and the range-azimuth heat map.

If `sensorStart` fails, the command line prints the failing step and an error code.

## Tests

```
make -C test
```

- `ddm_test` simulates DDM chirps for 3 TX and 4 RX (the firmware's phase codes, window and
  noise) across the full velocity range. It checks that each target's velocity is resolved to
  the correct sub-band and that the virtual-array phases match the simulated antennas.
- `rfparser_test` runs TI's chirp-configuration parser with stubbed SDK calls and checks TDM,
  DDM and invalid configurations.

## Limitations

- The detection accelerator holds at most 32 KB of detection matrix. Folding the sub-bands
  keeps DDM within that limit (256 range bins × 128 chirps folds to 256 × 32).
- A target between two Doppler bins can be reported one bin away, because the empty sub-band's
  noise contributes to the folded matrix.
- Velocity is resolved assuming one target per range/Doppler cell. Two targets at the same range
  whose sub-band copies overlap can be assigned the wrong velocity.
- On the AWR1843AOP the IF signal carries the negative of the programmed TX phase, so the
  firmware programs a decreasing phase ramp. Other devices may differ.

## License

The SDK sources are © Texas Instruments and distributed under the terms in their file headers.
