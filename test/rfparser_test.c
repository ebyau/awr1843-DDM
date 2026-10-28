/* SPDX-License-Identifier: MIT */
/*
 * Host unit test for the demo RF parser (mmwdemo_rfparser.c) with stubbed mmWave
 * control APIs: checks stock TDM-MIMO and DDM-MIMO chirp configurations against
 * the expected antenna layout or error code. Build and run: make -C test
 */
#include <stdio.h>
#include <string.h>
#include <ti/demo/utils/mmwdemo_rfparser.h>
#include <ti/utils/mathutils/mathutils.h>

#define MAX_CHIRPS 8U

static rlChirpCfg_t gChirps[MAX_CHIRPS];
static uint32_t gNumChirps;
static rlProfileCfg_t gProfile;
static int gProfileTag;
static int gFailures;

/* Stubs for the mmWave control and math utility calls the parser makes. */
int32_t MMWave_getNumChirps(MMWave_ProfileHandle h, uint32_t *n, int32_t *e)
{
    *n = gNumChirps;
    return 0;
}

int32_t MMWave_getChirpHandle(MMWave_ProfileHandle h, uint32_t i, MMWave_ChirpHandle *c, int32_t *e)
{
    *c = &gChirps[i - 1U];
    return 0;
}

int32_t MMWave_getChirpCfg(MMWave_ChirpHandle c, rlChirpCfg_t *cfg, int32_t *e)
{
    *cfg = *(rlChirpCfg_t *)c;
    return 0;
}

int32_t MMWave_getProfileCfg(MMWave_ProfileHandle h, rlProfileCfg_t *p, int32_t *e)
{
    *p = gProfile;
    return 0;
}

uint32_t mathUtils_floorLog2(uint32_t x)
{
    uint32_t r = 0U;
    while (x >>= 1U)
    {
        r++;
    }
    return r;
}

uint32_t mathUtils_ceilLog2(uint32_t x)
{
    uint32_t r = mathUtils_floorLog2(x);
    return ((1U << r) < x) ? r + 1U : r;
}

uint32_t mathUtils_pow2roundup(uint32_t x)
{
    return 1U << mathUtils_ceilLog2(x);
}

/* The stock AOP profile (profile_3d_aop.cfg) with numChirps chirps of the given TX masks,
 * 32 loops, all RX and TX channels enabled. */
static void setupConfig(MMWave_OpenCfg *open, MMWave_CtrlCfg *ctrl, MmwDemo_ADCBufCfg *adc,
                        const uint16_t *txMasks, uint32_t numChirps)
{
    uint32_t i;

    memset(open, 0, sizeof(*open));
    memset(ctrl, 0, sizeof(*ctrl));
    memset(adc, 0, sizeof(*adc));
    open->adcOutCfg.fmt.b2AdcBits = 2U;
    open->adcOutCfg.fmt.b2AdcOutFmt = 1U;
    open->chCfg.rxChannelEn = 0xFU;
    open->chCfg.txChannelEn = 0x7U;
    ctrl->dfeDataOutputMode = MMWave_DFEDataOutputMode_FRAME;
    ctrl->u.frameCfg.profileHandle[0] = &gProfileTag;
    ctrl->u.frameCfg.frameCfg.chirpStartIdx = 0U;
    ctrl->u.frameCfg.frameCfg.chirpEndIdx = numChirps - 1U;
    ctrl->u.frameCfg.frameCfg.numLoops = 32U;
    ctrl->u.frameCfg.frameCfg.framePeriodicity = 1000U * 200000U;
    adc->adcFmt = 0U;
    adc->iqSwapSel = 1U;
    adc->chInterleave = 1U;
    adc->chirpThreshold = 1U;

    memset(&gProfile, 0, sizeof(gProfile));
    gProfile.numAdcSamples = 256U;
    gProfile.digOutSampleRate = 7200U;
    gProfile.freqSlopeConst = 2047;
    gProfile.idleTimeConst = 700U;
    gProfile.rampEndTime = 3900U;

    gNumChirps = numChirps;
    for (i = 0U; i < numChirps; i++)
    {
        memset(&gChirps[i], 0, sizeof(gChirps[i]));
        gChirps[i].chirpStartIdx = (rlUInt16_t)i;
        gChirps[i].chirpEndIdx = (rlUInt16_t)i;
        gChirps[i].txEnable = txMasks[i];
    }
}

static void run(const char *name, const uint16_t *txMasks, uint32_t numChirps, uint8_t ddmBands,
                int32_t expRet, uint8_t expCubeTx, uint8_t expDdmTx)
{
    MMWave_OpenCfg open;
    MMWave_CtrlCfg ctrl;
    MmwDemo_ADCBufCfg adc;
    MmwDemo_RFParserOutParams out;
    int32_t ret;
    int ok;

    setupConfig(&open, &ctrl, &adc, txMasks, numChirps);
    memset(&out, 0, sizeof(out));
    out.ddmNumBands = ddmBands;

    ret = MmwDemo_RFParser_parseConfig(&out, 0, &open, &ctrl, &adc, 3.6f, false);
    ok = (ret == expRet) && ((ret != 0) || ((out.numTxAntennas == expCubeTx) && (out.ddmNumTx == expDdmTx)));
    printf("%s %-28s ret=%6d cubeTx=%u ddmNumTx=%u dopplerChirps=%u\n", ok ? "PASS" : "FAIL", name, ret,
           out.numTxAntennas, out.ddmNumTx, out.numDopplerChirps);
    gFailures += ok ? 0 : 1;
}

int main(void)
{
    const uint16_t stock[] = {1U, 2U, 4U};
    const uint16_t ddm[] = {7U, 7U, 7U, 7U};
    const uint16_t ddmTx02[] = {5U, 5U, 5U, 5U};
    const uint16_t ddmMixed[] = {7U, 7U, 3U, 7U};

    run("stock TDM 1,2,4",     stock,    3U, 0U, 0,                                                 3U, 0U);
    run("DDM all-TX, 4 bands", ddm,      4U, 4U, 0,                                                 1U, 3U);
    run("DDM all-TX, 3 bands", ddm,      4U, 3U, MMWDEMO_RFPARSER_EINVAL_NUM_TX_ANTENNAS,           0U, 0U);
    run("DDM TX0+TX2 only",    ddmTx02,  4U, 4U, MMWDEMO_RFPARSER_EINVAL_NUM_TX_ANTENNAS,           0U, 0U);
    run("DDM mixed chirps",    ddmMixed, 4U, 4U, MMWDEMO_RFPARSER_EINVAL__VALID_PROFILECFG_NOT_FOUND, 0U, 0U);
    return (gFailures != 0) ? 1 : 0;
}
