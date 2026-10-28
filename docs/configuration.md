# Configuration

The firmware is configured the same way as TI's out-of-box demo: a `.cfg` file of CLI commands
is sent line by line to the command port (`/dev/ttyUSB0`, 115200 baud), ending with
`sensorStart`. All of TI's commands work as documented in the mmWave SDK user guide. This page
covers what DDM adds and what it restricts.

## `ddmCfg`

```
ddmCfg <numBands>
```

| `numBands` | Effect |
|---|---|
| `0` (or no `ddmCfg` line) | Stock TDM-MIMO behaviour. The firmware sends TI's exact RF command sequence. |
| `4` | DDM-MIMO with 4 Doppler sub-bands: 3 TX copies and one empty sub-band. Tested on hardware. |
| `8`, `16` | More sub-bands than TX + 1. Accepted, but untested on hardware. |

`numBands` must divide 64, because the per-chirp phase step must be a whole number of the phase
shifter's 64 steps, and must be larger than the number of TX (at most 16). The TX0 sub-band is
found as the first of the strongest run of consecutive sub-bands, one per TX, so any value
above the number of TX resolves velocity. Extra empty sub-bands cost detection sensitivity:
the fold averages every sub-band, so empty ones add noise without adding signal.

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
| `dfeDataOutputMode` | `1` (legacy frame) | The phase codes are set per chirp definition of a legacy frame. Advanced frames and subframes (`3`) are not supported. |
| `channelCfg` | Enable the TX antennas used (shipped profile: `15 7 0`, 4 RX and 3 TX) | |
| `chirpCfg` | `numBands` chirp definitions. Every chirp enables the same TX set, contiguous from TX0 (TX mask `7` for 3 TX) | Phase codes are assigned by TX index; TX *k* goes to sub-band *k* |
| `frameCfg` | Exactly `numBands` chirps per loop (`chirpEndIdx − chirpStartIdx + 1 = numBands`) | The phase pattern repeats every `numBands` chirps |
| `cfarFovCfg <sf> 1 ...` | Doppler field of view covering the full velocity range (±20.6 m/s for the shipped profile) | CFAR runs on the folded matrix, before velocity is resolved. A narrower Doppler window filters on the folded (aliased) bin and can drop real targets. |
| `compRangeBiasAndRxChanPhase` | 12 values in virtual-array order (`tx * 4 + rx`), measured in TDM mode | Same virtual array as TDM, so TDM calibration values apply unchanged |
| `extendedMaxVelocity` | `0` (recommended) | This TDM feature extends velocity by testing TX motion-phase hypotheses; DDM already resolves the full chirp rate |

The detection matrix seen by CFAR is `numRangeBins × (numDopplerBins / numBands)` 16-bit
values and must fit the accelerator's 32 KB limit. The shipped profile uses 256 × 32 = 16 KB.

## Unsupported options

These assume one TX per chirp. When `ddmCfg` is active they are rejected at `sensorStart`.

| Option | Why it does not work with DDM | What to do |
|---|---|---|
| `measureRangeBiasAndRxChanPhase` enabled | Measures range bias and RX phase per TX from a TDM radar cube | Measure in TDM mode (no `ddmCfg`), then copy the values into `compRangeBiasAndRxChanPhase` of the DDM configuration |
| `clutterRemoval` enabled | Subtracts the mean over chirps. With DDM only TX0's static return survives that mean (TX1/TX2 are phase-coded and average out), so only TX0's copy is removed and the virtual array is distorted | Leave disabled |
| `calibDcRangeSig` enabled | Same chirp-mean estimate as clutter removal | Leave disabled |
| `guiMonitor` range-azimuth heat map (5th argument) | The heat map code assumes a TDM radar cube; the AoA unit rejects it | Set to `0`. The range-Doppler heat map (6th argument) works and shows all sub-bands. |

The first three print `Error: ddmCfg does not support measureRangeBiasAndRxChanPhase,
clutterRemoval or calibDcRangeSig`. The range-azimuth heat map is rejected by the DSP chain
during configuration.

DDM is also only available in the AOP image (`./build.sh`); the non-AOP image
(`./build.sh std`) fails `sensorStart` when `ddmCfg` is set.

## Worked example: converting a TDM profile

`host/profiles/ddm_aop.cfg` is TI's `profile_3d_aop.cfg` (in
`sdk/packages/ti/demo/xwr18xx/mmw/profiles/`) with these changes:

```diff
-chirpCfg 0 0 0 0 0 0 0 1
-chirpCfg 1 1 0 0 0 0 0 2
-chirpCfg 2 2 0 0 0 0 0 4
-frameCfg 0 2 32 0 100 1 0
-guiMonitor -1 1 1 1 0 0 1
+chirpCfg 0 0 0 0 0 0 0 7
+chirpCfg 1 1 0 0 0 0 0 7
+chirpCfg 2 2 0 0 0 0 0 7
+chirpCfg 3 3 0 0 0 0 0 7
+frameCfg 0 3 32 0 100 1 0
+guiMonitor -1 1 1 0 0 0 1
-cfarFovCfg -1 1 -7.06 12
+cfarFovCfg -1 1 -21.2 21.2
+ddmCfg 4
 sensorStart
```

Step by step:

1. **Chirps.** TDM uses three chirp definitions with TX masks 1, 2 and 4 (one TX each). DDM
   needs `numBands` = 4 definitions, all with mask `7` (TX0, TX1, TX2). The chirp profile
   (`profileCfg`) is unchanged.
2. **Frame.** `frameCfg 0 3 32 ...` loops chirps 0–3 32 times: 128 chirps per frame, a
   128-point Doppler FFT, 4 sub-bands of 32 bins. The frame period stays 100 ms.
3. **Doppler field of view.** The stock window (−7.06 to 12 m/s) is opened to the full
   ±21.2 m/s, slightly wider than the maximum velocity λ / (4 · Tc) ≈ 20.6 m/s (46 µs chirp
   period, λ ≈ 3.79 mm at the 79.1 GHz chirp centre frequency).
4. **Output.** The noise profile output (4th `guiMonitor` argument) is turned off in the
   shipped profile; the range-azimuth heat map stays off.
5. **Enable DDM.** `ddmCfg 4` before `sensorStart`.

`clutterRemoval`, `calibDcRangeSig` and `measureRangeBiasAndRxChanPhase` are already disabled
in TI's profile, so they need no change.

To run the same scene in TDM for comparison, send TI's profile to the same firmware:

```sh
uv run python host/mmw_host.py sdk/packages/ti/demo/xwr18xx/mmw/profiles/profile_3d_aop.cfg --frames 20
```

## Shipped profiles

All are in `host/profiles/` and use DDM with 3 TX and 4 sub-bands.

| File | Range bins | Frame period | Range-Doppler heat map | Use |
|---|---|---|---|---|
| `ddm_aop.cfg` | 256 (0.042 m, CFAR range window 0.25–15 m) | 100 ms | off | Point cloud, `mmw_host.py` |
| `ddm_aop_rdmap.cfg` | 256 | 1 s | on | `rd_view.py`, `ddm_check.py` |
| `ddm_phase2_aop.cfg` | 128 (CFAR range window 0.25–5 m) | 1 s | on | Shorter-range variant with a 32 KB heat map |
| `ddm_aop_raw.cfg` | 256 | 100 ms | off | `ddm_aop.cfg` with raw ADC streaming to a DCA1000EVM (`lvdsStreamCfg -1 0 1 0`) and only the point cloud on the data port, for `raw_capture.py` |

The range-Doppler heat map is 256 × 128 × 2 bytes = 64 KB per frame, about 0.7 s on the
921600-baud data port, so profiles that enable it run at 1 frame per second.

## Errors at `sensorStart`

If `sensorStart` fails, the CLI prints the failing step and an error code, for example
`Error: MmwDemo_configSensor failed [-50001]`.

| Message or code | Cause |
|---|---|
| `Error: numBands must be 0, or a divisor of 64 in (3, 16]` | Invalid `ddmCfg` argument (reported by `ddmCfg` itself) |
| `Error: DDM needs frameCfg with N chirps per loop` | `frameCfg` loop length differs from `numBands`, or not a legacy frame |
| `Error: ddmCfg does not support ...` | An unsupported option is enabled (see above) |
| `MmwDemo_configSensor failed [-50001]` | RF parser: TX set not contiguous from TX0, fewer than 2 TX, or not fewer TX than sub-bands |
| `MmwDemo_configSensor failed [-50013]` | RF parser: chirps enable different TX sets |
| `Error: rlRfSetMiscConfig retVal=...` / `Error: rlRfSetPhaseShiftConfig retVal=...` | The RF front end rejected the phase shifter configuration |
| `Error: mmWave Config failed [Error code: ... Subsystem: ...]` | TI mmWave control error (as in the stock demo, now printed on the CLI) |

`host/mmw_host.py` stops at the first command whose reply does not contain `Done` and prints
that reply.
