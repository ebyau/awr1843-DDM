# Architecture

This page explains how DDM-MIMO is split between the radar and the PC: the radar transmits the
phase-coded chirps and streams raw ADC samples, and the PC separates the transmitters and does
all the signal processing. It covers the signal model, the firmware, the raw data format, the
host decoder and where each part lives in the code. Firmware paths are relative to
`sdk/packages/ti/`.

## Terms

| Term | Meaning |
|---|---|
| TDM-MIMO | Time-division multiplexing: one TX antenna per chirp, TX antennas take turns. TI's stock demo. |
| DDM-MIMO | Doppler-division multiplexing: all TX antennas on every chirp, separated by a per-chirp phase code that shifts each TX in the Doppler spectrum. |
| Virtual array | The TX × RX antenna pairs used for angle estimation. 3 TX × 4 RX = 12 elements. On the AWR1843AOP the 3 TX form the horizontal (azimuth) axis and the 4 RX the vertical axis. |
| MSS | Master subsystem, ARM Cortex-R4F: runs this firmware (command line, RF configuration, LVDS stream). |
| DSS | DSP subsystem (C674x DSP and FFT accelerator). Unused: the image contains no DSP program. |
| BSS | Radar subsystem that runs the RF front end. Configured from the MSS through mmWaveLink (`rl*` calls). |
| CBUFF / LVDS | The hardware that copies each chirp's ADC samples from the ADC buffer onto the two LVDS lanes, without the CPU. |

## Signal model

The AWR1843 has a 6-bit phase shifter per TX (64 steps of 5.625°) that can be programmed per
chirp. With `ddmCfg N` (N sub-bands), the firmware programs TX *k* on chirp *n* of each loop to

    programmed phase = −n · k · 360° / N

On this device the IF signal carries the negative of the programmed phase, so in the received
data TX *k* advances by +*k* · 360°/N per chirp. A constant phase step per chirp is a frequency
shift in slow time: TX *k*'s copy of a target appears *k* · (Doppler bins / N) bins above the
TX0 copy, modulo the spectrum width. With N > number of TX, at least one sub-band contains no
copy.

The pattern repeats every N chirps, so it is set once with N static chirp definitions
(`chirpCfg 0..N-1`) looped by `frameCfg`; nothing changes at run time. N must divide 64 so that
the phase step is a whole number of phase shifter steps.

With the shipped profile (`profiles/template.toml`, N = 4, 32 loops):

| | TDM (stock `profile_3d_aop.cfg`) | DDM (`template.toml`) |
|---|---|---|
| TX per chirp | 1 | 3 |
| Chirps per frame | 96 (3 × 32) | 128 (4 × 32) |
| Doppler FFT | 32 bins per TX | 128 bins, 4 sub-bands of 32 |
| Max unambiguous velocity | ±6.9 m/s | ±5.96 m/s |
| Velocity resolution | 0.43 m/s | 0.093 m/s |
| Chirps per TX per frame | 32 | 128 |
| Motion phase between TX copies | compensated on the host | none (TX simultaneous) |
| Virtual array | 12 (3 TX × 4 RX) | 12, same geometry |
| Raw data per frame | 384 KB | 512 KB |

The stock TDM profile uses a 46 µs chirp period (7 µs idle + 39 µs ramp), 100 MHz/µs slope
and 0.042 m range bins; the DDM profile a 159 µs period (100 µs idle + 59 µs ramp),
67.012 MHz/µs slope and 0.044 m range bins. Both start at 77 GHz with 256 ADC samples. On the
stock 46 µs chirp, DDM reaches ±20.6 m/s with 0.32 m/s resolution.

## Firmware

The firmware is TI's `xwr18xx_mmw` demo (paths under `demo/xwr18xx/mmw/`) reduced to the MSS.
It has no on-chip processing: no range or Doppler FFT, no detection, no UART data output. On
`sensorStart` it:

1. Opens the RF front end on the first start (`MmwDemo_openSensor`): boot calibration or
   restore (`calibData`), and the HSI clock for the LVDS interface (`MmwDemo_mssSetHsiClk`).
2. Turns the per-chirp TX phase shifters on or off (`MmwDemo_ddmSetPhaseShifter`, through
   `rlRfSetMiscConfig`) and applies the profile, chirp and frame configuration (`MMWave_config`).
3. With `ddmCfg`, programs the phase code of every TX on every chirp definition
   (`MmwDemo_ddmConfigPhaseShift`, through `rlRfSetPhaseShiftConfig`). TX0 is never
   phase-shifted; `MmwDemo_ddmPhaseShift` computes the TX1/TX2 values.
4. Checks the configuration with TI's RF parser, which also enforces the DDM rules, and sets up
   the ADC buffer (`MmwDemo_rawDataConfig`).
5. Creates and activates the CBUFF hardware session (`mss/mmw_lvds_stream.c`) and starts the
   frames (`MMWave_start`). From then on every chirp's samples go out over LVDS with no
   software involved.

`sensorStop` stops the frames and deletes the CBUFF session.

Because nothing is processed on the chip, a frame only has to hold the chirp burst: the frame
period need not leave time for processing or for a UART transfer (only the radar subsystem's
about 0.3 ms blank time between frames), and the radar cube size is
not limited by on-chip memory.

## Raw data format

The DCA1000EVM receives the LVDS stream and forwards it over Ethernet; `host/ddm/dca.py` uses
the capture card driver from [xwr](https://github.com/RadarML/xwr). The capture card is started
after the radar has stopped and before it starts, so the byte count since the start marks the
frame boundaries.

Each frame is `[chirp, rx, sample]` complex 16-bit samples, chirps in transmit order
(chirp *n* uses chirp definition *n* mod N). On the wire the two lanes give the order
Q0 Q1 I0 I1 Q2 Q3 I2 I3 …, which `iiqq_to_complex` turns into complex samples. `ddm capture`
saves the frames with the configuration text in a `.npz` file.

## Host processing

`host/ddm/dsp.py` holds the decoder; `ddm decode` runs it on a capture and `ddm live` on every
frame. [raw_data.ipynb](raw_data.ipynb) walks through the same steps in plain numpy.

| Step | Function | What it does |
|---|---|---|
| Range and Doppler FFT | `doppler_spectrum` | Hann-windowed FFTs over samples and chirps: `[Doppler, rx, range]` |
| Static removal (optional) | `remove_static` | Subtracts each chirp definition's mean over the loops; this removes every TX copy of a static target |
| Fold | `fold` | Averages the N sub-bands: the copies of one target land on the same folded bin |
| Detection | `find_targets` | Peaks `DETECTION_DB` above the median of the folded map, beyond `MIN_RANGE_M` (TX-to-RX leakage) |
| TX0 sub-band | `tx0_band` | The first sub-band of the strongest run of `numTx` consecutive sub-bands (cyclic) |
| Virtual array | `ddm_virtual_array` | Reads TX *k*'s copy from sub-band TX0 + *k*: `[folded bin, range, tx, rx]` |
| Velocity | `signed_doppler_bin` | TX0's unfolded Doppler bin gives the velocity over the full ±λ / (4 · Tc) |
| Angle | `decode_frame` | FFT across the 3 TX of the virtual array gives azimuth |

TDM frames (no `ddmCfg`) take `tdm_spectrum` (a Doppler FFT over the loops for each TX) and
`tdm_virtual_array`, which removes the target's motion between the TX chirps.

## Changed files

Paths are under `sdk/packages/ti/`. Apart from these, the only modified SDK file is
`sdk/packages/scripts/unix/setenv.sh` (build environment, see
[development.md](development.md#environment)).

| File | Change |
|---|---|
| `demo/xwr18xx/mmw/mss/mss_main.c` | MSS-only firmware: sensor open/config/start/stop, DDM phase shifters, ADC buffer and LVDS setup |
| `demo/xwr18xx/mmw/mss/mmw_cli.c` | Sensor and stream commands only, plus `ddmCfg` |
| `demo/xwr18xx/mmw/mss/mmw_mss.h`, `include/mmw_config.h` | Control block and configuration types without the processing chain |
| `demo/xwr18xx/mmw/mss/mmw_lvds_stream.{c,h}` | LVDS hardware session only (raw ADC data) |
| `demo/xwr18xx/mmw/mmw_res.h` | LVDS EDMA resources only |
| `demo/xwr18xx/mmw/makefile`, `mss/mmw_mss.mak`, `mss/mmw_mss_linker.cmd` | Builds the MSS image; the image has no DSP program |
| `demo/utils/mmwdemo_rfparser.{c,h}` | `ddmNumBands` input, `ddmNumTx` output and the DDM chirp checks; a frame with more than 32 chirps per loop now stops parsing with the error instead of continuing past it |

The demo's DSS sources, its documentation, the processing chain under `datapath/`, and the
example profiles are removed.

To see every line changed against TI's sources, see
[development.md](development.md#comparing-with-tis-sdk).
