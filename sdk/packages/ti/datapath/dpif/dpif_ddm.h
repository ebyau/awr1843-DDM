/* SPDX-License-Identifier: MIT */
/**
 *   @file  dpif_ddm.h
 *
 *   @brief
 *      Doppler-division multiplexing (DDM) MIMO helpers shared by the
 *      object detection chain.
 *
 *      With DDM every TX transmits on every chirp. TX k is phase-coded so that
 *      its copy of a target appears k sub-bands above the TX0 copy in the
 *      Doppler spectrum (modulo the spectrum width). With more sub-bands than
 *      TX antennas at least one sub-band stays empty, so the TX copies form the
 *      only run of numTx occupied sub-bands; its first band holds TX0, which
 *      resolves the Doppler ambiguity over the full spectrum.
 *
 *      All functions are pure and hardware independent.
 */
#ifndef DPIF_DDM_H
#define DPIF_DDM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*! @brief Largest supported number of Doppler sub-bands */
#define DPIF_DDM_MAX_BANDS      16U

/**
 *  @b Description
 *  @n
 *      Folds a range-major detection matrix of numBands Doppler sub-bands into
 *      a single sub-band by averaging the log-magnitudes of the bands, so the
 *      output keeps the input Q-format.
 *
 *  @param[in]  in              Detection matrix, numRangeBins x (bandWidth << log2NumBands)
 *  @param[out] out             Folded detection matrix, numRangeBins x bandWidth
 *  @param[in]  numRangeBins    Number of range bins
 *  @param[in]  bandWidth       Number of Doppler bins per sub-band
 *  @param[in]  log2NumBands    Log2 of the number of sub-bands
 */
static inline void DPIF_ddmFoldDetMatrix(const uint16_t *in, uint16_t *out,
                                         uint32_t numRangeBins, uint32_t bandWidth,
                                         uint32_t log2NumBands)
{
    uint32_t numBands = 1U << log2NumBands;
    uint32_t rangeIdx;
    uint32_t binIdx;
    uint32_t bandIdx;

    for (rangeIdx = 0U; rangeIdx < numRangeBins; rangeIdx++)
    {
        for (binIdx = 0U; binIdx < bandWidth; binIdx++)
        {
            uint32_t sum = 0U;

            for (bandIdx = 0U; bandIdx < numBands; bandIdx++)
            {
                sum += in[bandIdx * bandWidth + binIdx];
            }
            out[binIdx] = (uint16_t)(sum >> log2NumBands);
        }
        in  += bandWidth << log2NumBands;
        out += bandWidth;
    }
}

/**
 *  @b Description
 *  @n
 *      Finds the sub-band holding the TX0 copy of a target: the first band of
 *      the numTx cyclically consecutive sub-bands with the most power. With one
 *      spare sub-band this is the band after the empty one.
 *
 *  @param[in]  bandPower   Target power in each sub-band at the folded Doppler bin
 *  @param[in]  numBands    Number of sub-bands
 *  @param[in]  numTx       Number of DDM TX antennas, less than numBands
 *
 *  @retval     Sub-band index of TX0, 0 .. numBands-1
 */
static inline uint32_t DPIF_ddmTx0Band(const float *bandPower, uint32_t numBands, uint32_t numTx)
{
    uint32_t bestBand = 0U;
    float    bestPower = -1.0f;
    uint32_t startBand;
    uint32_t txIdx;

    for (startBand = 0U; startBand < numBands; startBand++)
    {
        float    power = 0.0f;
        uint32_t band = startBand;

        for (txIdx = 0U; txIdx < numTx; txIdx++)
        {
            power += bandPower[band];
            band = (band + 1U == numBands) ? 0U : band + 1U;
        }
        if (power > bestPower)
        {
            bestPower = power;
            bestBand = startBand;
        }
    }
    return bestBand;
}

/**
 *  @b Description
 *  @n
 *      Sub-band holding the copy transmitted by a given TX.
 *
 *  @param[in]  tx0Band     Sub-band of TX0 from @ref DPIF_ddmTx0Band
 *  @param[in]  txIdx       TX antenna index
 *  @param[in]  numBands    Number of sub-bands
 *
 *  @retval     Sub-band index, 0 .. numBands-1
 */
static inline uint32_t DPIF_ddmTxBand(uint32_t tx0Band, uint32_t txIdx, uint32_t numBands)
{
    return (tx0Band + txIdx) % numBands;
}

/**
 *  @b Description
 *  @n
 *      Doppler bin of the copy transmitted by a given TX.
 *
 *  @param[in]  foldedBin   Doppler bin within the sub-band, 0 .. bandWidth-1
 *  @param[in]  tx0Band     Sub-band of TX0 from @ref DPIF_ddmTx0Band
 *  @param[in]  txIdx       TX antenna index
 *  @param[in]  bandWidth   Number of Doppler bins per sub-band
 *  @param[in]  numBands    Number of sub-bands
 *
 *  @retval     Doppler bin, 0 .. bandWidth*numBands-1
 */
static inline uint32_t DPIF_ddmTxDopplerBin(uint32_t foldedBin, uint32_t tx0Band, uint32_t txIdx,
                                            uint32_t bandWidth, uint32_t numBands)
{
    return foldedBin + bandWidth * DPIF_ddmTxBand(tx0Band, txIdx, numBands);
}

#ifdef __cplusplus
}
#endif

#endif /* DPIF_DDM_H */
