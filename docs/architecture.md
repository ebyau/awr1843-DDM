# Architecture

The radar transmits phase-coded chirps and streams raw ADC samples; all processing is on the PC.
Firmware paths are relative to `sdk/packages/ti/`.

## Terms

| Term | Meaning |
|---|---|
| TDM-MIMO | One TX per chirp, taking turns (TI's demo). |
| DDM-MIMO | All TX on every chirp, separated by a per-chirp phase code that shifts each TX in Doppler. |
| Virtual array | TX × RX antenna pairs: 3 × 4 = 12. |
| MSS | ARM Cortex-R4F; runs this firmware (CLI, RF configuration, LVDS stream). |
| DSS | DSP subsystem; unused, the image has no DSP program. |
| BSS | Radar subsystem running the RF front end; configured from the MSS through mmWaveLink (`rl*`). |
| CBUFF / LVDS | Hardware that copies each chirp's ADC samples onto the two LVDS lanes, without the CPU. |

## Signal model

Each TX has a 6-bit phase shifter (64 steps of 5.625°), programmable per chirp. With
`ddmCfg N`, TX *k* on chirp *n* of each loop gets

    programmed phase = −n · k · 360° / N

The AWR1843AOP inverts the programmed phase in the IF signal, so TX *k* advances by
+*k* · 360°/N per chirp. That shifts its copy of every target *k* · (Doppler bins / N) bins
above TX0's, modulo the spectrum width. With N > TX count, at least one sub-band stays empty.

The pattern repeats every N chirps: N static chirp definitions (`chirpCfg 0..N-1`) looped by
`frameCfg`, nothing changed at run time. N divides 64 so the step is a whole number of
phase-shifter steps.

| | TDM (stock `profile_3d_aop.cfg`) | DDM (`template.toml`, N = 4, 32 loops) |
|---|---|---|
| TX per chirp | 1 | 3 |
| Chirps per frame | 96 (3 × 32) | 128 (4 × 32) |
| Doppler FFT | 32 bins per TX | 128 bins, 4 sub-bands of 32 |
| Max velocity | ±6.9 m/s | ±5.96 m/s |
| Velocity resolution | 0.43 m/s | 0.093 m/s |
| Motion phase between TX copies | one chirp period per TX | none (TX simultaneous) |
| Raw data per frame | 384 KB | 512 KB |

Chirps: TDM 46 µs period (7 idle + 39 ramp), 100 MHz/µs, 0.042 m range bins; DDM 159 µs
(100 + 59), 67.012 MHz/µs, 0.044 m. Both 77 GHz, 256 samples. On the 46 µs chirp, DDM reaches
±20.6 m/s at 0.32 m/s resolution.

## Firmware

TI's `xwr18xx_mmw` demo (`demo/xwr18xx/mmw/`) reduced to the MSS, with no on-chip processing.
On `sensorStart` it:

1. Opens the RF front end on the first start (`MmwDemo_openSensor`): calibration or restore
   (`calibData`), HSI clock for LVDS.
2. Checks the configuration with TI's RF parser, including the DDM rules, and sets up the ADC
   buffer (`MmwDemo_rawDataConfig`). A rejected configuration stops here, before the BSS.
3. Turns the phase shifters on or off (`MmwDemo_ddmSetPhaseShifter`) and applies profile,
   chirps and frame (`MMWave_config`).
4. With `ddmCfg`, programs every TX's phase on every chirp (`MmwDemo_ddmConfigPhaseShift`).
5. Activates the CBUFF session (`mss/mmw_lvds_stream.c`); on failure it reports an error and
   sends no chirp. Then starts the frames (`MMWave_start`).

`sensorStop` stops the frames, waits up to 3 s for the last one, and deletes the CBUFF session.

With no on-chip processing, a frame only needs the chirp burst plus the BSS's ~0.3 ms blank,
and frame size is not limited by on-chip memory.

## Raw data format

The DCA1000EVM forwards the LVDS stream over Ethernet; `host/ddm/dca.py` reads it with
[xwr](https://github.com/RadarML/xwr). The card starts before the radar, so the byte count
marks frame boundaries.

A frame is `[chirp, rx, sample]` complex int16, chirps in transmit order (chirp *n* uses
definition *n* mod N). The lanes arrive as Q0 Q1 I0 I1 Q2 Q3 I2 I3 …; `iiqq_to_iq` reorders
them to (I, Q). Capture file format: [development.md](development.md#raw-data-capture).
