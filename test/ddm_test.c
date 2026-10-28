/* SPDX-License-Identifier: MIT */
/*
 * Host unit test for dpif_ddm.h: simulates DDM chirps (3 TX, 4 RX, 4 sub-bands,
 * 128 chirps, firmware phase codes) and checks Doppler disambiguation and the
 * 12-element virtual array. Build and run: make -C test
 */
#include <complex.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include <ti/datapath/dpif/dpif_ddm.h>

#define NUM_TX        3U
#define NUM_RX        4U
#define NUM_BANDS     4U
#define LOG2_BANDS    2U
#define NUM_CHIRPS    128U
#define BAND_WIDTH    (NUM_CHIRPS / NUM_BANDS)
#define NUM_RANGE     1U

static double complex spectrum[NUM_RX][NUM_CHIRPS];

/* Firmware phase code for TX k on chirp n: -n*k*360/numBands degrees, 6-bit quantized.
 * Measured on the AWR1843AOP: a programmed phase p shows up as -p in the IF signal. */
static double txPhase(uint32_t tx, uint32_t chirp)
{
    uint32_t lsb = (64U - (tx * chirp * (64U / NUM_BANDS)) % 64U) % 64U;
    return 2.0 * M_PI * lsb / 64.0;
}

static double noise(void)
{
    return ((double)rand() / RAND_MAX - 0.5) * 0.05;
}

/* Chirp samples -> windowed DFT per RX, as the Doppler stage computes it. */
static void simulate(double dopplerBin, const double antPhase[NUM_TX][NUM_RX])
{
    double complex samples[NUM_CHIRPS];

    for (uint32_t rx = 0U; rx < NUM_RX; rx++)
    {
        for (uint32_t n = 0U; n < NUM_CHIRPS; n++)
        {
            double complex s = noise() + I * noise();
            for (uint32_t tx = 0U; tx < NUM_TX; tx++)
            {
                s += cexp(I * (2.0 * M_PI * dopplerBin * n / NUM_CHIRPS - txPhase(tx, n) + antPhase[tx][rx]));
            }
            samples[n] = s * (0.5 - 0.5 * cos(2.0 * M_PI * n / NUM_CHIRPS));
        }
        for (uint32_t k = 0U; k < NUM_CHIRPS; k++)
        {
            double complex acc = 0.0;
            for (uint32_t n = 0U; n < NUM_CHIRPS; n++)
            {
                acc += samples[n] * cexp(-I * 2.0 * M_PI * k * n / NUM_CHIRPS);
            }
            spectrum[rx][k] = acc;
        }
    }
}

/* Runs the receive chain on the simulated spectrum; returns the signed TX0 Doppler bin. */
static int32_t process(double complex virtualAnt[NUM_TX][NUM_RX])
{
    uint16_t detMatrix[NUM_RANGE * NUM_CHIRPS];
    uint16_t folded[NUM_RANGE * BAND_WIDTH];
    float bandPower[NUM_BANDS];
    uint32_t peak = 0U;

    for (uint32_t k = 0U; k < NUM_CHIRPS; k++)
    {
        double sum = 0.0;
        for (uint32_t rx = 0U; rx < NUM_RX; rx++)
        {
            sum += log2(cabs(spectrum[rx][k]) + 1e-9);
        }
        detMatrix[k] = (uint16_t)(sum * 256.0 / NUM_RX + 2048.0);
    }
    DPIF_ddmFoldDetMatrix(detMatrix, folded, NUM_RANGE, BAND_WIDTH, LOG2_BANDS);
    for (uint32_t d = 1U; d < BAND_WIDTH; d++)
    {
        peak = (folded[d] > folded[peak]) ? d : peak;
    }

    for (uint32_t b = 0U; b < NUM_BANDS; b++)
    {
        bandPower[b] = 0.0f;
        for (uint32_t rx = 0U; rx < NUM_RX; rx++)
        {
            bandPower[b] += (float)pow(cabs(spectrum[rx][peak + b * BAND_WIDTH]), 2);
        }
    }
    uint32_t tx0Band = DPIF_ddmTx0Band(bandPower, NUM_BANDS, NUM_TX);

    for (uint32_t tx = 0U; tx < NUM_TX; tx++)
    {
        uint32_t bin = DPIF_ddmTxDopplerBin(peak, tx0Band, tx, BAND_WIDTH, NUM_BANDS);
        for (uint32_t rx = 0U; rx < NUM_RX; rx++)
        {
            virtualAnt[tx][rx] = spectrum[rx][bin];
        }
    }
    int32_t bin = (int32_t)(peak + BAND_WIDTH * tx0Band);
    return (bin >= (int32_t)(NUM_CHIRPS / 2U)) ? bin - (int32_t)NUM_CHIRPS : bin;
}

/* TX0 band search for other band counts: numTx occupied bands among numBands,
 * starting at every possible band, with the spare bands at noise level. */
static uint32_t checkTx0BandSearch(void)
{
    static const uint32_t layouts[][2] = {{2U, 4U}, {2U, 8U}, {3U, 8U}, {3U, 16U}};
    uint32_t failures = 0U;

    for (uint32_t i = 0U; i < sizeof(layouts) / sizeof(layouts[0]); i++)
    {
        uint32_t numTx = layouts[i][0];
        uint32_t numBands = layouts[i][1];

        for (uint32_t tx0Band = 0U; tx0Band < numBands; tx0Band++)
        {
            float bandPower[DPIF_DDM_MAX_BANDS];

            for (uint32_t b = 0U; b < numBands; b++)
            {
                bandPower[b] = 0.01f * (float)rand() / (float)RAND_MAX;
            }
            for (uint32_t tx = 0U; tx < numTx; tx++)
            {
                bandPower[DPIF_ddmTxBand(tx0Band, tx, numBands)] = 1.0f + 0.5f * (float)rand() / (float)RAND_MAX;
            }
            if (DPIF_ddmTx0Band(bandPower, numBands, numTx) != tx0Band)
            {
                failures++;
                printf("FAIL band search: %u TX, %u bands, TX0 in band %u\n", numTx, numBands, tx0Band);
            }
        }
    }
    return failures;
}

static double wrap(double a)
{
    return atan2(sin(a), cos(a));
}

int main(void)
{
    uint32_t failures = 0U;
    uint32_t adjacent = 0U;
    uint32_t cases = 0U;
    double worstPhaseErr = 0.0;

    srand(1U);
    for (int32_t v = -(int32_t)(NUM_CHIRPS / 2U); v < (int32_t)(NUM_CHIRPS / 2U); v++)
    {
        for (int32_t frac = -1; frac <= 1; frac++)
        {
            double dopplerBin = v + 0.3 * frac;
            double antPhase[NUM_TX][NUM_RX];
            double complex virtualAnt[NUM_TX][NUM_RX];

            for (uint32_t tx = 0U; tx < NUM_TX; tx++)
            {
                for (uint32_t rx = 0U; rx < NUM_RX; rx++)
                {
                    antPhase[tx][rx] = 2.0 * M_PI * rand() / RAND_MAX;
                }
            }
            simulate(dopplerBin, antPhase);
            int32_t got = process(virtualAnt);
            cases++;

            /* An off-grid target may land on the neighbouring bin; anything
             * further means the sub-band disambiguation failed. */
            int32_t err = got - v;
            if (abs(err) > 1)
            {
                failures++;
                printf("FAIL velocity: true bin %+.1f, recovered %+d\n", dopplerBin, got);
                continue;
            }
            adjacent += (err != 0) ? 1U : 0U;
            /* Relative phases across the virtual array must match the planted ones. */
            for (uint32_t tx = 0U; tx < NUM_TX; tx++)
            {
                for (uint32_t rx = 0U; rx < NUM_RX; rx++)
                {
                    double err = wrap(carg(virtualAnt[tx][rx] / virtualAnt[0][0]) -
                                      (antPhase[tx][rx] - antPhase[0][0]));
                    worstPhaseErr = fmax(worstPhaseErr, fabs(err));
                }
            }
        }
    }
    printf("%u cases: %u disambiguation failures, %u off by one bin; worst virtual-array phase error %.2f deg\n",
           cases, failures, adjacent, worstPhaseErr * 180.0 / M_PI);

    uint32_t searchFailures = checkTx0BandSearch();
    printf("TX0 band search, 2-3 TX in 4-16 bands: %u failures\n", searchFailures);
    failures += searchFailures;
    return (failures == 0U && worstPhaseErr < 5.0 * M_PI / 180.0) ? 0 : 1;
}
