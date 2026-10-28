/*
 * Host unit test for the demo RF parser (mmwdemo_rfparser.c) with stubbed mmWave
 * control APIs: checks stock TDM-MIMO and DDM-MIMO chirp configurations against
 * the expected antenna layout or error code. Build and run: make -C test
 */
#include <stdio.h>
#include <string.h>
#include <ti/demo/utils/mmwdemo_rfparser.h>
#include <ti/utils/mathutils/mathutils.h>

static rlChirpCfg_t gChirps[8]; static uint32_t gNumChirps;
static rlProfileCfg_t gProfile;
static int gProfileTag;

int32_t MMWave_getNumChirps(MMWave_ProfileHandle h, uint32_t *n, int32_t *e) { *n = gNumChirps; return 0; }
int32_t MMWave_getChirpHandle(MMWave_ProfileHandle h, uint32_t i, MMWave_ChirpHandle *c, int32_t *e) { *c = &gChirps[i-1]; return 0; }
int32_t MMWave_getChirpCfg(MMWave_ChirpHandle c, rlChirpCfg_t *cfg, int32_t *e) { *cfg = *(rlChirpCfg_t *)c; return 0; }
int32_t MMWave_getProfileCfg(MMWave_ProfileHandle h, rlProfileCfg_t *p, int32_t *e) { *p = gProfile; return 0; }
uint32_t mathUtils_floorLog2(uint32_t x) { uint32_t r = 0; while (x >>= 1) r++; return r; }
uint32_t mathUtils_ceilLog2(uint32_t x) { uint32_t r = mathUtils_floorLog2(x); return ((1u << r) < x) ? r + 1 : r; }
uint32_t mathUtils_pow2roundup(uint32_t x) { return 1u << mathUtils_ceilLog2(x); }

static int failures;

static void run(const char *name, const uint16_t *tx, uint32_t n, uint8_t bands,
                int32_t expRet, uint8_t expCubeTx, uint8_t expDdmTx)
{
    MMWave_OpenCfg open; MMWave_CtrlCfg ctrl; MmwDemo_ADCBufCfg adc; MmwDemo_RFParserOutParams out;
    memset(&open, 0, sizeof open); memset(&ctrl, 0, sizeof ctrl); memset(&adc, 0, sizeof adc); memset(&out, 0, sizeof out); out.ddmNumBands = bands;
    open.adcOutCfg.fmt.b2AdcBits = 2; open.adcOutCfg.fmt.b2AdcOutFmt = 1;
    open.chCfg.rxChannelEn = 0xF; open.chCfg.txChannelEn = 0x7;
    ctrl.dfeDataOutputMode = MMWave_DFEDataOutputMode_FRAME;
    ctrl.u.frameCfg.profileHandle[0] = &gProfileTag;
    ctrl.u.frameCfg.frameCfg.chirpStartIdx = 0; ctrl.u.frameCfg.frameCfg.chirpEndIdx = n - 1;
    ctrl.u.frameCfg.frameCfg.numLoops = 32; ctrl.u.frameCfg.frameCfg.framePeriodicity = 1000 * 200000;
    adc.adcFmt = 0; adc.iqSwapSel = 1; adc.chInterleave = 1; adc.chirpThreshold = 1;
    memset(&gProfile, 0, sizeof gProfile);
    gProfile.numAdcSamples = 256; gProfile.digOutSampleRate = 7200; gProfile.freqSlopeConst = 2047;
    gProfile.idleTimeConst = 700; gProfile.rampEndTime = 3900;
    gNumChirps = n;
    for (uint32_t i = 0; i < n; i++) { memset(&gChirps[i], 0, sizeof gChirps[i]); gChirps[i].chirpStartIdx = gChirps[i].chirpEndIdx = i; gChirps[i].txEnable = tx[i]; }
    int32_t rv = MmwDemo_RFParser_parseConfig(&out, 0, &open, &ctrl, &adc, 3.6f, false);
    int ok = (rv == expRet) && ((rv != 0) || ((out.numTxAntennas == expCubeTx) && (out.ddmNumTx == expDdmTx)));
    printf("%s %-28s ret=%6d cubeTx=%u ddmNumTx=%u dopplerChirps=%u\n", ok ? "PASS" : "FAIL", name, rv,
           out.numTxAntennas, out.ddmNumTx, out.numDopplerChirps);
    failures += ok ? 0 : 1;
}

int main(void)
{
    const uint16_t stock[] = {1, 2, 4}, ddm[] = {7, 7, 7, 7};
    const uint16_t ddmTx02[] = {5, 5, 5, 5}, ddmMixed[] = {7, 7, 3, 7};
    run("stock TDM 1,2,4",           stock,    3, 0, 0,      3, 0);
    run("DDM all-TX, 4 bands",       ddm,      4, 4, 0,      1, 3);
    run("DDM all-TX, 3 bands",       ddm,      4, 3, -50001, 0, 0);
    run("DDM TX0+TX2 only",          ddmTx02,  4, 4, -50001, 0, 0);
    run("DDM mixed chirps",          ddmMixed, 4, 4, -50013, 0, 0);
    return failures ? 1 : 0;
}
