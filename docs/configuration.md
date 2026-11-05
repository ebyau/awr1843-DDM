# Configuration

The radar is configured the same way as TI's out-of-box demo: a `.cfg` file of CLI commands is
sent line by line to the command port (`/dev/ttyUSB0`, 115200 baud), ending with
`sensorStart`. The firmware only sets up the sensor and streams the raw ADC samples of every
chirp over LVDS to a DCA1000EVM. It does no signal processing, so TI's processing and output
commands (`guiMonitor`, `cfarCfg`, `aoaFovCfg`, `clutterRemoval`, ...) do not exist and are
rejected. The host tools read the radar parameters from the same `.cfg` text.

## Commands

| Command | Notes |
|---|---|
| `sensorStop`, `flushCfg` | Start every configuration with these. |
| `dfeDataOutputMode 1` | Legacy frame only. Advanced frames (`3`) are rejected at `sensorStart`. |
| `channelCfg`, `adcCfg`, `lowPower` | Fixed by the first `sensorStart` after power-up. To change them, reset the radar. The host tools expect complex samples (`adcCfg 2 1`). |
| `adcbufCfg -1 <fmt> <swap> <interleave> 1` | Chirp threshold must be `1`. The host tools expect complex samples (`fmt 0`). |
| `profileCfg`, `chirpCfg`, `frameCfg` | As in TI's mmWave SDK user guide. For DDM, see the rules below. |
| `lvdsStreamCfg -1 <header> 1 0` | Streams ADC samples (format `1`) with no software session (`0`). The host tools expect `header` `0`. |
| `calibData <save> <restore> <flashOffset>` | RF calibration save/restore, as in TI's demo. `calibData 0 0 0` turns it off. |
| `ddmCfg <numBands>` | DDM-MIMO phase coding; see below. |
| `sensorStart [0]` | Applies the configuration and starts streaming. `sensorStart 0` restarts the previous configuration. |
| `queryDemoStatus` | Prints the sensor state and the number of frames streamed. |

`sensorStart` without an argument needs `adcbufCfg`, `lvdsStreamCfg` and `calibData` to be
sent again since the last `sensorStop`, together with the sensor commands.

## `ddmCfg`

```
ddmCfg <numBands>
```

| `numBands` | Effect |
|---|---|
| `0` (or no `ddmCfg` line) | TDM-MIMO, or a single TX: no phase coding. |
| `4` | DDM-MIMO with 4 Doppler sub-bands: 3 TX copies and one empty sub-band. Tested on hardware. |
| `8`, `16` | More sub-bands than TX + 1. Accepted, but untested on hardware. |

`numBands` must divide 64 and be larger than the number of TX (at most 16). **TI hardware
limit:** each TX has a 6-bit phase shifter, so a phase can only be set in 64 steps of 5.625°.
The phase step between chirps is 360° / `numBands`, which is a whole number of steps only if
`numBands` divides 64.

With more sub-bands than TX, the TX copies of a target sit in consecutive sub-bands and at
least one sub-band stays empty, which marks where TX0's copy starts.

Behaviour:

- `ddmCfg` must come before `sensorStart`. While the sensor is running it is ignored with
  `Ignored: This command is not allowed after sensor has started`.
- `sensorStop` resets `numBands` to 0. A configuration that uses DDM must include `ddmCfg`
  every time it is sent. (TI's `flushCfg` is handled inside the CLI library and does not
  reset it; `sensorStop` does.)
- Switching from a DDM configuration back to TDM (`sensorStop`, then a configuration without
  `ddmCfg`) turns the phase shifters off again at the next `sensorStart`.

## Rules for a DDM configuration

| Command | Requirement | Why |
|---|---|---|
| `dfeDataOutputMode` | `1` (legacy frame) | The phase codes are set per chirp definition of a legacy frame. |
| `channelCfg` | Enable the TX antennas used (shipped profile: `15 7 0`, 4 RX and 3 TX) | |
| `chirpCfg` | `numBands` chirp definitions. Every chirp enables the same TX set, contiguous from TX0 (TX mask `7` for 3 TX) | Phase codes are assigned by TX index; TX *k* goes to sub-band *k* |
| `frameCfg` | Exactly `numBands` chirps per loop (`chirpEndIdx − chirpStartIdx + 1 = numBands`) | The phase pattern repeats every `numBands` chirps |

To run the same scene in TDM for comparison, set `tdm = true` in a copy of the profile: one
chirp definition per TX (masks 1, 2, 4), `frameCfg 0 2 ...` and no `ddmCfg`.

## Profiles

The host tools take either a TI `.cfg` file or a TOML profile. A profile describes the radar in a
few lines, with units in the key names, and is rendered to `.cfg` text when a command runs
(rendered files are not stored).

`ddm cfg PROFILE` checks a profile, logs the derived numbers (chirp period, chirp burst, frame
rate, range and velocity resolution, sub-band span, raw frame size and raw data rate) and prints
the `.cfg` text; `-o FILE` writes it to a file. TI `.cfg` files are sent as they are.

```toml
description = "Shown as % comments at the top of the .cfg"

[chirp]                        # profileCfg
start_ghz = 77
idle_us = 100
adc_start_us = 5.7
ramp_end_us = 59
slope_mhz_per_us = 67.012
tx_start_us = 1
samples = 256
sample_rate_ksps = 5000
rx_gain_db = 30

[mimo]
tx = [0, 1, 2]                 # channelCfg TX and RX antennas
rx = [0, 1, 2, 3]
bands = 4                      # DDM sub-bands (ddmCfg)
tdm = false                    # true: TI's TDM, one chirp per TX, no ddmCfg

[frame]
loops = 32
period_ms = 125

[extra]
lines = ["calibData 1 0 0x1F0000"]  # TI commands that replace the generated ones or are added
```

`profiles/template.toml` holds `[chirp]` and `[frame]`, which are required, and the `tdm` and
`bands` settings; the other keys and tables have the defaults shown above. `[chirp]` also takes
`tx_power_backoff`, `tx_phase_shifter`, `hpf1_corner` and `hpf2_corner` (default 0).

The rendered `.cfg` holds only the commands the firmware accepts, with fixed values for the ones
the format does not describe (`adcCfg 2 1`, `adcbufCfg -1 0 1 1 1`, `lowPower 0 0`,
`lvdsStreamCfg -1 0 1 0`, `calibData 0 0 0`). A line in `[extra]` replaces every generated line
of the same command; other commands are added before `sensorStart`, which `[extra]` must not
contain.

### Limits

`ddm cfg`, `ddm capture` and `ddm live` check the configuration against these limits. For a TOML profile a violation is
an error; for a `.cfg` file it is a warning, and the file is sent anyway.

| Limit | Why |
|---|---|
| DDM: `bands` divides 64, and number of TX < `bands` ≤ 16 | **TI hardware limit:** the 6-bit phase shifter has 64 steps, so the phase step 360° / `bands` must be a whole number of steps (see [`ddmCfg`](#ddmcfg)) |
| DDM: at least 2 TX, contiguous from TX0 | Phase codes are assigned by TX index |
| At most 32 chirps per loop | Size of the chirp table in the firmware's RF parser (a firmware limit, not a hardware one) |
| DDM: `bands` chirps per loop, all with the same TX mask | The phase pattern repeats every `bands` chirps (see [rules](#rules-for-a-ddm-configuration)) |
| 1–255 loops per frame | **TI hardware limit:** `frameCfg` loop count |
| `samples` × 4 B, rounded up to 16 B, × number of RX ≤ 16 KB | **TI hardware limit:** the 32 KB ADC buffer works as two halves (ping-pong): one chirp fills one half while the other is streamed out. Complex samples take 4 B and each RX's block is padded to 16 B, so 4 RX allow at most 1024 samples per chirp. |
| `idle_us` ≤ 5242.87 µs | **TI hardware limit:** `profileCfg` idle time is a 19-bit count of 10 ns steps (0–524287) |
| `ramp_end_us` ≤ 5000 µs | **TI hardware limit:** `profileCfg` ramp end time is at most 500000 steps of 10 ns |
| `adc_start_us` + `samples` / sample rate ≤ `ramp_end_us` | ADC sampling must end before the ramp does, or the last samples see no chirp |
| Chirp within 76–81 GHz | **TI hardware limit:** RF band of the device, from the start frequency to the end of the ramp. The slope may be negative (a down-chirp); then the ramp ends below the start frequency. |
| Chirps per frame × chirp period + 0.3 ms ≤ frame period | **TI hardware limit:** the chirp burst must fit in the frame, and the radar subsystem needs about 0.3 ms of blank time between frames. No processing time is needed beyond that: the radar only streams the samples. |

These are also TI hardware limits, from TI's `rl_sensor.h`, but are not checked by the tools:

| Limit | Value |
|---|---|
| `adc_start_us` | 0–40.95 µs |
| `sample_rate_ksps` | Complex ADC output (`adcCfg 2 1`): at most 12500 ksps |
| Data rate | The raw data rate (`ddm cfg` shows it) must fit through the LVDS link to the DCA1000EVM and on to the PC over gigabit Ethernet (at most 125 MB/s, less in practice). The shipped profile needs about 4 MB/s. |

## Velocity range and resolution

With chirp period Tc = `idle_us` + `ramp_end_us` and wavelength λ ≈ 3.8 mm:

| | Maximum velocity | Velocity resolution |
|---|---|---|
| DDM | λ / (4 · Tc) | λ / (2 · `bands` · `loops` · Tc) |
| TDM | λ / (4 · N_TX · Tc) | λ / (2 · N_TX · `loops` · Tc) |

Raising the idle time lowers the velocity range and refines the velocity resolution by the
same factor, without changing range. Example settings for `profiles/template.toml`:

| Settings | Velocity | Frame period | Use |
|---|---|---|---|
| As shipped: `idle_us = 100`, `loops = 32`, `period_ms = 125` | ±5.96 m/s, 0.093 m/s per bin | 125 ms (8 frames/s) | General use; range up to 11.2 m in 0.044 m bins |
| `idle_us = 415`, `loops = 16`, `period_ms = 50` | ±2 m/s, 0.062 m/s per bin (1 m/s sub-bands) | 50 ms | Slow targets such as hand gestures. Not yet tested on hardware. |
| `tdm = true` | ±1.99 m/s, 0.12 m/s per bin | 125 ms | TI's TDM-MIMO, to compare the same scene without DDM |

## Errors at `sensorStart`

If `sensorStart` fails, the CLI prints the reason, then the failing step, for example
`Error: invalid profile, chirp or frame configuration [Error:-50001]` followed by
`Error: MmwDemo_configSensor failed [-1]`.

| Message or code | Cause |
|---|---|
| `Error: numBands must be 0, or a divisor of 64 in (3, 16]` | Invalid `ddmCfg` argument (reported by `ddmCfg` itself) |
| `Error: DDM needs frameCfg with N chirps per loop` | `frameCfg` loop length differs from `numBands` |
| `Error: invalid profile, chirp or frame configuration [Error:-50001]` | TX set not contiguous from TX0, fewer than 2 TX, or not fewer TX than sub-bands |
| `Error: invalid profile, chirp or frame configuration [Error:-50013]` | Chirps enable different TX sets |
| `Error: only a legacy frame is supported (dfeDataOutputMode 1)` | Advanced frame configuration |
| `Error: Full configuration (including adcbufCfg, lvdsStreamCfg and calibData) must be provided before sensorStart` | A required command is missing |
| `Error: channelCfg, adcCfg and lowPower cannot change after the first sensorStart; reset the device` | These are fixed after the first start |
| `Error: rlRfSetMiscConfig retVal=...` / `Error: rlRfSetPhaseShiftConfig retVal=...` | The RF front end rejected the phase shifter configuration |
| `Error: mmWave Config failed [Error code: ... Subsystem: ...]` | TI mmWave control error |

The host tools stop at the first command whose reply does not contain `Done` and print that
reply. A radar that does not reply at all needs a reset (NRST button or power cycle).
