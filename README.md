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

- Ubuntu x86-64, an AWR1843AOPEVM on a DCA1000EVM, the card on Ethernet per xwr's
  [setup guide](https://radarml.github.io/xwr/setup/).
- In `~/ti`: [mmWave SDK 03.06.02](https://www.ti.com/tool/MMWAVE-SDK) and
  [UniFlash 9.7](https://www.ti.com/tool/UNIFLASH) (`~/ti/uniflash_9.7.0`).
- System packages, serial access, [uv](https://docs.astral.sh/uv/), and a udev rule that keeps
  ModemManager off the board's CP2105:

  ```sh
  sudo dpkg --add-architecture i386 && sudo apt update
  sudo apt install libc6:i386 libstdc++6:i386 make mono-runtime gcc
  sudo usermod -aG dialout $USER     # then log out and in
  echo 'ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea70", ENV{ID_MM_DEVICE_IGNORE}="1"' \
    | sudo tee /etc/udev/rules.d/71-mm-ignore-cp2105.rules
  sudo udevadm control --reload-rules
  ```

- The repository holds only the modified SDK files. Clone it and fill in the rest:

  ```sh
  git clone https://github.com/ebyau/awr1843-DDM.git && cd awr1843-DDM
  cp -r ~/ti/mmwave_sdk_03_06_02_00-LTS/firmware ~/ti/mmwave_sdk_03_06_02_00-LTS/packages sdk/
  git checkout -- sdk
  ```

Details: [docs/development.md](docs/development.md#environment).

### 2. Build and flash

```sh
./build.sh          # -> out/xwr18xx_mmw_demo.bin
```

Power off the capture card, set SOP0 on, SOP1 off, SOP2 on, replug USB, run `./flash.sh`.
Then set SOP2 off and replug. Problems: [flashing](docs/development.md#flashing).

### 3. Run

Set up the capture card network first (static IP, socket buffer):
[raw data capture](docs/development.md#raw-data-capture).

```sh
uv run ddm cfg profiles/template.toml                         # check limits, print numbers and .cfg
uv run ddm live profiles/template.toml                        # live raw spectrum
uv run ddm capture profiles/template.toml -n 50 -o wave.npz   # record 50 frames
uv run ddm show wave.npz                                      # replay a capture
```

Captures default to `captures/YYYYmmdd-HHMMSS_<profile>.npz`.

## Host tools

| Command | Purpose |
|---|---|
| `ddm cfg PROFILE [-o FILE]` | Check a profile, print derived numbers, write the `.cfg` |
| `ddm capture PROFILE` | Record raw ADC frames |
| `ddm live PROFILE` | Live unwindowed range-Doppler spectrum of RX 0 |
| `ddm show CAPTURE.npz` | Replay a capture, or save a frame as PNG |

Options: `-v` (debug), `-q` (quiet); `--cli PORT` for `capture` and `live`; `--tdm` to allow a
`.cfg` without `ddmCfg`. `uv run ddm COMMAND --help` lists all.

A `PROFILE` is a TOML file (`profiles/template.toml`) or a TI `.cfg` file. Copy the template to
make your own. DDM is the default; `tdm = true` in `[mimo]` selects TDM. All keys and limits:
[profiles](docs/configuration.md#profiles).

## Documentation

| Page | Contents |
|---|---|
| [architecture.md](docs/architecture.md) | How DDM works, the firmware, the raw data format |
| [configuration.md](docs/configuration.md) | Commands, `ddmCfg`, DDM rules, profiles, hardware limits |
| [development.md](docs/development.md) | Layout, toolchain, flashing, host tools, tests |

## Limitations

- The AWR1843AOP inverts the programmed TX phase in the IF signal; the firmware compensates.
  Other devices may differ.
- Legacy frames only (no advanced frames or sub-frames).

## License

Project code: [MIT](LICENSE) (files with an `SPDX-License-Identifier: MIT` line). Files under
`sdk/` from TI's mmWave SDK, modified or not, stay © Texas Instruments under the BSD-style
license in their headers.
