# DDM-MIMO raw-data firmware for the AWR1843AOP

Firmware for the TI AWR1843AOPEVM (77 GHz) that transmits with Doppler-division multiplexing
(DDM) MIMO and streams raw ADC samples to a [DCA1000EVM](https://www.ti.com/tool/DCA1000EVM).
The radar does no processing; Python tools on the PC capture the data and plot its raw spectrum.
Built on TI's `xwr18xx_mmw` demo (mmWave SDK 03.06.02): same `.cfg` commands, plus `ddmCfg`.

## What DDM changes

To use its 3 TX × 4 RX = 12-element virtual array, the radar must tell the TX apart.

- **TDM** (TI's demo): TX take turns, one per chirp. Velocity range: ±6.9 m/s.
- **DDM** (this firmware): all TX on every chirp; TX *k* gets a phase step that shifts its copy
  *k* Doppler sub-bands up. 4 sub-bands: 3 TX copies, 1 empty, which marks TX0. Velocity
  range: ±20.6 m/s.

(Velocities for TI's stock AOP chirp.)

## Quick start

### 1. Prerequisites

- Ubuntu x86-64 (tested on 26.04), an AWR1843AOPEVM connected over USB and mounted on a
  DCA1000EVM, with the capture card on Ethernet as described in xwr's
  [setup guide](https://radarml.github.io/xwr/setup/).
- TI tools installed under `~/ti`: [mmWave SDK 03.06.02](https://www.ti.com/tool/MMWAVE-SDK)
  (installs the ARM compiler, SYS/BIOS and XDCtools it needs) and
  [UniFlash 9.7](https://www.ti.com/tool/UNIFLASH) in `~/ti/uniflash_9.7.0`.
- System packages, serial port access and [uv](https://docs.astral.sh/uv/):

  ```sh
  sudo dpkg --add-architecture i386
  sudo apt update
  sudo apt install libc6:i386 libstdc++6:i386 make mono-runtime gcc
  sudo usermod -aG dialout $USER     # then log out and back in
  ```

- A udev rule so ModemManager leaves the board's USB-UART bridge (CP2105) alone:

  ```sh
  echo 'ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea70", ENV{ID_MM_DEVICE_IGNORE}="1"' \
    | sudo tee /etc/udev/rules.d/71-mm-ignore-cp2105.rules
  sudo udevadm control --reload-rules
  ```

- The repository tracks only the SDK directories it modifies. Fill in the rest of `sdk/` from
  your SDK install, then restore the modified files:

  ```sh
  cp -r ~/ti/mmwave_sdk_03_06_02_00-LTS/firmware ~/ti/mmwave_sdk_03_06_02_00-LTS/packages sdk/
  git checkout -- sdk
  ```

Details and alternatives: [docs/development.md](docs/development.md#environment).

### 2. Build

```sh
./build.sh          # -> out/xwr18xx_mmw_demo.bin
```

### 3. Flash

Power off the capture card. Set the SOP switches to flashing mode (SOP0 on, SOP1 off, SOP2 on), unplug and replug USB, then:

```sh
./flash.sh
```

Set the switches back to normal mode (SOP0 on, SOP1 off, SOP2 off) and replug USB again.
See [flashing](docs/development.md#flashing) if it fails.

### 4. Check the profile

The host tools are one command, `ddm`, installed into the project environment by uv. Start
with the shipped profile:

```sh
uv run ddm cfg profiles/template.toml
```

This checks the profile against the hardware limits and prints its range and velocity
resolution, maximum velocity and the TI `.cfg` text it sends.

### 5. Capture and view raw data

The radar streams its ADC samples to the capture card (see
[raw data capture](docs/development.md#raw-data-capture) for its setup):

```sh
uv run ddm capture profiles/template.toml -n 50 -o wave.npz   # 50 frames of ADC samples
uv run ddm show wave.npz                                      # replay its raw spectrum
uv run ddm live profiles/template.toml                        # raw spectrum live; close the window to stop
```

Without `-o`, captures are saved as `captures/YYYYmmdd-HHMMSS_<profile>.npz`.

## Host tools

All host tools are subcommands of `ddm`; `uv run ddm COMMAND --help` lists the options.

| Command | Purpose |
|---|---|
| `ddm cfg PROFILE [-o FILE]` | Check a profile against the hardware limits, show its derived numbers, write the `.cfg` |
| `ddm capture PROFILE` | Record raw ADC frames through a DCA1000EVM |
| `ddm live PROFILE` | Live unwindowed range-Doppler spectrum of RX 0 |
| `ddm show CAPTURE.npz` | The same plot for a saved capture, replayed in a loop or saved as a PNG |

Every command takes `-v` for debug output (each command sent to the radar, tracebacks) or `-q`
for warnings and errors only, after the command name: `uv run ddm capture -v PROFILE`. `--cli` selects another serial port.

### Profiles

A `PROFILE` is a short TOML file or a TI `.cfg` file. `profiles/template.toml` is the one
shipped profile: the chirp, the DDM/TDM switch and the frame. A `.cfg` file is sent as it is;
it may only use the [commands the firmware accepts](docs/configuration.md#commands).

To change velocity range or resolution, copy the template, edit it, check it, then run it. Every
command sends the profile to the radar itself; there is no separate load step.

```sh
cp profiles/template.toml profiles/mine.toml     # edit the chirp and frame values
uv run ddm cfg profiles/mine.toml                # limits, range/velocity resolution, .cfg text
uv run ddm capture profiles/mine.toml            # or live
```

DDM is the default (`[mimo] bands = 4`); set `tdm = true` in `[mimo]` for TI's time-division
MIMO with one TX per chirp. The tools read the mode from the configuration. See
[profiles](docs/configuration.md#profiles) for every key and the hardware limits.

## Documentation

| Page | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | How DDM works, what the firmware does, and the raw data format |
| [docs/configuration.md](docs/configuration.md) | The firmware's commands, `ddmCfg`, rules for DDM chirp configurations, the TOML profile format and the hardware limits |
| [docs/development.md](docs/development.md) | Repository layout, toolchain, flashing details, host tools, tests, linting, coding conventions, and how to extend the firmware |

## Limitations

- On the AWR1843AOP the IF signal carries the negative of the programmed TX phase, so the
  firmware programs a decreasing phase ramp. Other devices may behave differently.
- Only legacy frames are supported (no advanced frames or sub-frames).

## License

The code written for this project is released under the [MIT License](LICENSE); those files
carry an `SPDX-License-Identifier: MIT` line. The files under `sdk/` that come from the TI
mmWave SDK, including the ones modified here, remain © Texas Instruments under the terms stated
in their file headers (a BSD-style license that requires the copyright notice to be kept in
source and binary redistributions).
