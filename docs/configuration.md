# Configuration

A `.cfg` file of CLI commands is sent line by line to `/dev/ttyUSB0` (115200 baud), ending with
`sensorStart`, as in TI's demo. The firmware does no processing, so TI's processing commands
(`guiMonitor`, `cfarCfg`, `clutterRemoval`, ...) are rejected.

## Commands

| Command | Notes |
|---|---|
| `sensorStop`, `flushCfg` | Start every configuration with these. |
| `dfeDataOutputMode 1` | Legacy frame only. |
| `channelCfg`, `adcCfg`, `lowPower` | Fixed by the first `sensorStart`; reset the radar to change them. Host tools need `adcCfg 2 1`. |
| `adcbufCfg -1 0 1 1 1` | Complex, Q first, RX not interleaved, chirp threshold 1 (what the host tools decode). |
| `profileCfg`, `chirpCfg`, `frameCfg` | As in TI's SDK user guide; DDM rules below. |
| `lvdsStreamCfg -1 0 1 0` | ADC samples, no header, no software session. |
| `calibData <save> <restore> <offset>` | RF calibration save/restore; `0 0 0` turns it off. |
| `ddmCfg <numBands>` | DDM phase coding; see below. |
| `sensorStart [0]` | Apply and start. `sensorStart 0` restarts the last configuration that started. |
| `queryDemoStatus` | Sensor state and frames streamed. |

A plain `sensorStart` needs `adcbufCfg`, `lvdsStreamCfg` and `calibData` sent since the last
successful start. A failed start keeps the configuration for a retry.

Errors are always reported, never as `Done`: a rejected configuration leaves the BSS unchanged;
a failed LVDS setup stops `sensorStart` before any chirp; `sensorStop` reports an RF that did
not stop or a last frame that did not end within 3 s.

## `ddmCfg`

| `numBands` | Effect |
|---|---|
| `0` | TDM, or a single TX: no phase coding. |
| `4` | 4 sub-bands: 3 TX copies, 1 empty. Tested on hardware. |
| `8`, `16` | Accepted, untested on hardware. |

`numBands` must divide 64 and exceed the TX count (max 16). **TI hardware limit:** the phase
shifter has 64 steps of 5.625°, so the step 360°/`numBands` must be a whole number of steps.

- `ddmCfg` applies to the next reconfiguring `sensorStart`, wherever it appears before it. A
  successful start uses it up, so every DDM configuration includes it; one without it runs TDM.
  A failed start keeps it for the retry.
- Send `ddmCfg 0` for TDM (TOML profiles do), so a value left from a failed start can't apply.
- Ignored while the sensor runs.

## DDM rules

| Command | Requirement | Why |
|---|---|---|
| `dfeDataOutputMode` | `1` | Phase codes are set per chirp definition of a legacy frame. |
| `chirpCfg` | `numBands` definitions, all with the same TX mask, contiguous from TX0 (`7` for 3 TX) | Codes are assigned by TX index. |
| `frameCfg` | `numBands` chirps per loop | The pattern repeats every `numBands` chirps. |

**TDM is a diagnostic mode** (hardware checks, phase calibration, single-TX micro-Doppler). Choose
it explicitly: `tdm = true` in a profile, or `ddmCfg 0` / `--tdm` with a `.cfg`. Captures record
their mode.

## Profiles

The host tools take a TI `.cfg` file (sent as is) or a TOML profile (rendered to `.cfg` when a
command runs). `ddm cfg PROFILE` checks it, logs derived numbers and prints the `.cfg`
(`-o FILE` writes it).

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
tx = [0, 1, 2]                 # channelCfg TX and RX
rx = [0, 1, 2, 3]
bands = 4                      # ddmCfg
tdm = false                    # true: one chirp per TX, ddmCfg 0

[frame]
loops = 32
period_ms = 125

[extra]
lines = ["calibData 1 0 0x1F0000"]  # replace generated lines of the same command, or add
```

`[chirp]` and `[frame]` are required; other keys default as shown. `[chirp]` also takes
`tx_power_backoff`, `tx_phase_shifter`, `hpf1_corner`, `hpf2_corner` (default 0). Fixed lines:
`adcCfg 2 1`, `adcbufCfg -1 0 1 1 1`, `lowPower 0 0`, `lvdsStreamCfg -1 0 1 0`,
`calibData 0 0 0`. `[extra]` must not contain `sensorStart`.

### Limits

Checked by `cfg`, `capture` and `live`: errors for TOML profiles, warnings for `.cfg` files.

| Limit | Why |
|---|---|
| DDM: `bands` divides 64, TX count < `bands` ≤ 16 | **TI hardware limit:** 64-step phase shifter |
| DDM: ≥ 2 TX, contiguous from TX0; `bands` chirps per loop, same TX mask | Firmware DDM rules |
| ≤ 32 chirps per loop | Firmware chirp table |
| 1–255 loops | **TI hardware limit** (`frameCfg`) |
| `samples` even | Two LVDS lanes carry sample pairs |
| `samples` × 4 B (padded to 16 B) × RX ≤ 16 KB | **TI hardware limit:** half of the 32 KB ping-pong ADC buffer holds one chirp (≤ 1024 samples with 4 RX) |
| `idle_us` ≤ 5242.87, `ramp_end_us` ≤ 5000 | **TI hardware limit** (`profileCfg`, 10 ns steps) |
| ADC sampling ends before the ramp | Otherwise the last samples see no chirp |
| Chirp within 76–81 GHz | **TI hardware limit** (RF band; negative slopes allowed) |
| Chirps × chirp period + 0.3 ms ≤ frame period | **TI hardware limit:** BSS blank time between frames |

Not checked (TI `rl_sensor.h`): `adc_start_us` 0–40.95 µs; complex sample rate ≤ 12500 ksps;
the data rate (`ddm cfg` shows it) must fit gigabit Ethernet (≤ 125 MB/s; the template needs
about 4 MB/s).

## Velocity

With Tc = `idle_us` + `ramp_end_us` and λ ≈ 3.8 mm:

| | Max velocity | Resolution |
|---|---|---|
| DDM | λ / (4 Tc) | λ / (2 · `bands` · `loops` · Tc) |
| TDM | λ / (4 N_TX Tc) | λ / (2 N_TX · `loops` · Tc) |

More idle time trades velocity range for resolution, range unchanged.

| Settings | Velocity | Use |
|---|---|---|
| Template (`idle_us = 100`, `loops = 32`, 125 ms) | ±5.96 m/s, 0.093 m/s/bin | General; 11.2 m range, 0.044 m bins |
| `idle_us = 415`, `loops = 16`, 50 ms | ±2 m/s, 0.062 m/s/bin | Slow targets (gestures); untested |
| `tdm = true` | ±1.99 m/s, 0.12 m/s/bin | TDM comparison |

## Errors at `sensorStart`

The CLI prints the reason, then the failing step (e.g. `Error: MmwDemo_configSensor failed [-1]`).

| Message | Cause |
|---|---|
| `numBands must be 0, or a divisor of 64 in (3, 16]` | Invalid `ddmCfg` |
| `DDM needs frameCfg with N chirps per loop` | Loop length ≠ `numBands` |
| `invalid profile, chirp or frame configuration [Error:-50001]` | TX not contiguous from TX0, < 2 TX, or TX ≥ sub-bands |
| `... [Error:-50013]` | Chirps with different TX sets |
| `only a legacy frame is supported` | Advanced frame |
| `Full configuration ... must be provided before sensorStart` | Missing command |
| `channelCfg, adcCfg and lowPower cannot change after the first sensorStart` | Reset the device |
| `LVDS stream configuration failed` / `could not start` | CBUFF session error |
| `rlRfSetMiscConfig` / `rlRfSetPhaseShiftConfig retVal=...` | RF front end rejected the phase shifters |
| `mmWave Config failed` | TI mmWave control error |

The host tools stop at the first reply without `Done` and print it. No reply at all: reset the
radar (NRST or power cycle).
