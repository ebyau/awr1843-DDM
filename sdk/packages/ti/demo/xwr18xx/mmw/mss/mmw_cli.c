/*
 *   @file  mmw_cli.c
 *
 *   @brief
 *      Mmw (Milli-meter wave) DEMO CLI Implementation
 *
 *  \par
 *  NOTE:
 *      (C) Copyright 2018 Texas Instruments, Inc.
 *
 *  Redistribution and use in source and binary forms, with or without
 *  modification, are permitted provided that the following conditions
 *  are met:
 *
 *    Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *
 *    Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the
 *    distribution.
 *
 *    Neither the name of Texas Instruments Incorporated nor the names of
 *    its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 *  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 *  A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 *  OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 *  SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 *  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 *  DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 *  THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 *  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 *  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/**************************************************************************
 *************************** Include Files ********************************
 **************************************************************************/

/* Standard Include Files. */
#include <stdint.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>

/* BIOS/XDC Include Files. */
#include <xdc/runtime/System.h>

/* mmWave SDK Include Files: */
#include <ti/common/sys_common.h>
#include <ti/common/mmwave_sdk_version.h>
#include <ti/drivers/uart/UART.h>
#include <ti/utils/cli/cli.h>

/* Demo Include Files */
#include <ti/demo/xwr18xx/mmw/include/mmw_config.h>
#include <ti/demo/xwr18xx/mmw/mss/mmw_mss.h>
#include <ti/demo/utils/mmwdemo_adcconfig.h>

/**************************************************************************
 *************************** Local function prototype****************************
 **************************************************************************/

/* CLI Extended Command Functions */
static int32_t MmwDemo_CLISensorStart (int32_t argc, char* argv[]);
static int32_t MmwDemo_CLISensorStop (int32_t argc, char* argv[]);
static int32_t MmwDemo_CLIADCBufCfg (int32_t argc, char* argv[]);
static int32_t MmwDemo_CLILvdsStreamCfg (int32_t argc, char* argv[]);
static int32_t MmwDemo_CLIQueryDemoStatus (int32_t argc, char* argv[]);
static int32_t MmwDemo_CLICalibDataSaveRestore (int32_t argc, char* argv[]);
static int32_t MmwDemo_CLIDdmCfg (int32_t argc, char* argv[]);

/**************************************************************************
 *************************** Extern Definitions *******************************
 **************************************************************************/

extern MmwDemo_MSS_MCB    gMmwMssMCB;

/**************************************************************************
 *************************** CLI  Function Definitions **************************
 **************************************************************************/

/**
 *  @b Description
 *  @n
 *      Checks the sub-frame argument of a command. Only the legacy frame is
 *      supported, so it must be -1 (frame level) or 0.
 *
 *  @param[in] argc         Number of arguments
 *  @param[in] argv         Arguments
 *  @param[in] expectedArgc Expected number of arguments
 *
 *  @retval
 *      Success -   0
 *  @retval
 *      Error   -   <0
 */
static int32_t MmwDemo_CLICheckSubframe (int32_t argc, char* argv[], int32_t expectedArgc)
{
    int32_t subFrameNum;

    if (argc != expectedArgc)
    {
        CLI_write ("Error: Invalid usage of the CLI command\n");
        return -1;
    }

    subFrameNum = (int32_t) atoi (argv[1]);
    if ((subFrameNum != -1) && (subFrameNum != 0))
    {
        CLI_write ("Error: only the legacy frame is supported, subFrameIdx must be -1 or 0\n");
        return -1;
    }
    return 0;
}

/**
 *  @b Description
 *  @n
 *      This is the CLI Handler for the sensor start command. Without an argument the
 *      sensor is configured from the commands issued since the last stop, which must
 *      include adcbufCfg, lvdsStreamCfg and calibData. "sensorStart 0" restarts the
 *      sensor with its previous configuration.
 *
 *  @param[in] argc
 *      Number of arguments
 *  @param[in] argv
 *      Arguments
 *
 *  @retval
 *      Success -   0
 *  @retval
 *      Error   -   <0
 */
static int32_t MmwDemo_CLISensorStart (int32_t argc, char* argv[])
{
    bool        doReconfig = true;
    bool        isCfgPending;
    int32_t     retVal;

    if (argc == 2)
    {
        if (atoi (argv[1]) != 0)
        {
            CLI_write ("Error: Reconfig is not supported, only argument of 0 is\n"
                       "(do not reconfig, just re-start the sensor) valid\n");
            return -1;
        }
        doReconfig = false;
    }

    if (gMmwMssMCB.sensorState == MmwDemo_SensorState_STARTED)
    {
        CLI_write ("Ignored: Sensor is already started\n");
        return 0;
    }

    isCfgPending = (gMmwMssMCB.isAdcBufCfgPending == 1) && (gMmwMssMCB.isLvdsStreamCfgPending == 1) &&
                   (gMmwMssMCB.isCalibCfgPending == 1);
    if (doReconfig && !isCfgPending)
    {
        CLI_write ("Error: Full configuration (including adcbufCfg, lvdsStreamCfg and calibData) "
                   "must be provided before sensorStart\n");
        return -1;
    }
    if (!doReconfig && (gMmwMssMCB.sensorState != MmwDemo_SensorState_STOPPED))
    {
        CLI_write ("Error: \"sensorStart 0\" needs a sensor that was started and stopped before\n");
        return -1;
    }

    /***********************************************************************************
     * Retreive and check mmwave Open related config before calling openSensor
     ***********************************************************************************/
    if (gMmwMssMCB.sensorState == MmwDemo_SensorState_INIT)
    {
        /* Get the open configuration: */
        CLI_getMMWaveExtensionOpenConfig (&gMmwMssMCB.cfg.openCfg);
        retVal = MmwDemo_openSensor(true);
        if (retVal != 0)
        {
            CLI_write ("Error: MmwDemo_openSensor failed [%d]\n", retVal);
            return -1;
        }
        gMmwMssMCB.sensorState = MmwDemo_SensorState_OPENED;
    }
    else
    {
        /* channelCfg, adcCfg and lowPower only take effect on the first start
         * (MMWave_open); a change needs a reset of the device. */
        MMWave_OpenCfg openCfg;
        CLI_getMMWaveExtensionOpenConfig (&openCfg);
        if ((memcmp((void *)&gMmwMssMCB.cfg.openCfg.chCfg, (void *)&openCfg.chCfg, sizeof(rlChanCfg_t)) != 0) ||
            (memcmp((void *)&gMmwMssMCB.cfg.openCfg.lowPowerMode, (void *)&openCfg.lowPowerMode,
                    sizeof(rlLowPowerModeCfg_t)) != 0) ||
            (memcmp((void *)&gMmwMssMCB.cfg.openCfg.adcOutCfg, (void *)&openCfg.adcOutCfg,
                    sizeof(rlAdcOutCfg_t)) != 0))
        {
            CLI_write ("Error: channelCfg, adcCfg and lowPower cannot change after the first "
                       "sensorStart; reset the device\n");
            return -1;
        }
    }

    /***********************************************************************************
     * Retrieve mmwave Control related config before calling startSensor
     ***********************************************************************************/
    if (doReconfig)
    {
        CLI_getMMWaveExtensionConfig (&gMmwMssMCB.cfg.ctrlCfg);
        retVal = MmwDemo_configSensor();
        if (retVal != 0)
        {
            CLI_write ("Error: MmwDemo_configSensor failed [%d]\n", retVal);
            return -1;
        }
        gMmwMssMCB.isAdcBufCfgPending = 0;
        gMmwMssMCB.isLvdsStreamCfgPending = 0;
        gMmwMssMCB.isCalibCfgPending = 0;
    }
    retVal = MmwDemo_startSensor();
    if (retVal != 0)
    {
        CLI_write ("Error: MmwDemo_startSensor failed [%d]\n", retVal);
        return -1;
    }

    gMmwMssMCB.sensorState = MmwDemo_SensorState_STARTED;
    return 0;
}

/**
 *  @b Description
 *  @n
 *      This is the CLI Handler for the sensor stop command
 *
 *  @param[in] argc
 *      Number of arguments
 *  @param[in] argv
 *      Arguments
 *
 *  @retval
 *      Success -   0
 *  @retval
 *      Error   -   <0
 */
static int32_t MmwDemo_CLISensorStop (int32_t argc, char* argv[])
{
    /* flushCfg is handled by the CLI library, so DDM is cleared here instead:
     * every configuration that wants DDM must issue ddmCfg again. */
    gMmwMssMCB.ddmNumBands = 0U;

    if ((gMmwMssMCB.sensorState == MmwDemo_SensorState_STOPPED) ||
        (gMmwMssMCB.sensorState == MmwDemo_SensorState_INIT) ||
        (gMmwMssMCB.sensorState == MmwDemo_SensorState_OPENED))
    {
        CLI_write ("Ignored: Sensor is already stopped\n");
        return 0;
    }

    MmwDemo_stopSensor();

    gMmwMssMCB.sensorState = MmwDemo_SensorState_STOPPED;
    return 0;
}

/**
 *  @b Description
 *  @n
 *      This is the CLI Handler for the ADC buffer configuration
 *      (adcbufCfg <subFrameIdx> <adcOutputFmt> <SampleSwap> <ChanInterleave> <ChirpThreshold>)
 *
 *  @param[in] argc
 *      Number of arguments
 *  @param[in] argv
 *      Arguments
 *
 *  @retval
 *      Success -   0
 *  @retval
 *      Error   -   <0
 */
static int32_t MmwDemo_CLIADCBufCfg (int32_t argc, char* argv[])
{
    MmwDemo_ADCBufCfg   adcBufCfg;

    if (gMmwMssMCB.sensorState == MmwDemo_SensorState_STARTED)
    {
        CLI_write ("Ignored: This command is not allowed after sensor has started\n");
        return 0;
    }

    if (MmwDemo_CLICheckSubframe(argc, argv, 6) < 0)
    {
        return -1;
    }

    memset ((void *)&adcBufCfg, 0, sizeof(adcBufCfg));
    adcBufCfg.adcFmt          = (uint8_t) atoi (argv[2]);
    adcBufCfg.iqSwapSel       = (uint8_t) atoi (argv[3]);
    adcBufCfg.chInterleave    = (uint8_t) atoi (argv[4]);
    adcBufCfg.chirpThreshold  = (uint8_t) atoi (argv[5]);

    /* One chirp per ADC buffer event: the stream format the host tools expect */
    if (adcBufCfg.chirpThreshold != 1)
    {
        CLI_write("Error: chirpThreshold must be 1\n");
        return -1;
    }

    gMmwMssMCB.adcBufCfg = adcBufCfg;
    gMmwMssMCB.isAdcBufCfgPending = 1;
    return 0;
}

/**
 *  @b Description
 *  @n
 *      This is the CLI Handler for the LVDS raw data stream
 *      (lvdsStreamCfg <subFrameIdx> <enableHeader> <dataFmt> <enableSW>). Only raw
 *      ADC samples (dataFmt 1) without a software session (enableSW 0) are supported.
 *
 *  @param[in] argc
 *      Number of arguments
 *  @param[in] argv
 *      Arguments
 *
 *  @retval
 *      Success -   0
 *  @retval
 *      Error   -   <0
 */
static int32_t MmwDemo_CLILvdsStreamCfg (int32_t argc, char* argv[])
{
    MmwDemo_LvdsStreamCfg   cfg;

    if (gMmwMssMCB.sensorState == MmwDemo_SensorState_STARTED)
    {
        CLI_write ("Ignored: This command is not allowed after sensor has started\n");
        return 0;
    }

    if (MmwDemo_CLICheckSubframe(argc, argv, 5) < 0)
    {
        return -1;
    }

    memset ((void *)&cfg, 0, sizeof(MmwDemo_LvdsStreamCfg));
    cfg.isHeaderEnabled = (bool)    atoi(argv[2]);
    cfg.dataFmt         = (uint8_t) atoi(argv[3]);
    if ((cfg.dataFmt != MMW_DEMO_LVDS_STREAM_CFG_DATAFMT_ADC) || (atoi(argv[4]) != 0))
    {
        CLI_write ("Error: only raw ADC data is streamed: lvdsStreamCfg -1 <enableHeader> 1 0\n");
        return -1;
    }

    gMmwMssMCB.lvdsStreamCfg = cfg;
    gMmwMssMCB.isLvdsStreamCfgPending = 1;
    return 0;
}

/**
 *  @b Description
 *  @n
 *      This is the CLI Handler for the status query
 *
 *  @param[in] argc
 *      Number of arguments
 *  @param[in] argv
 *      Arguments
 *
 *  @retval
 *      Success -   0
 */
static int32_t MmwDemo_CLIQueryDemoStatus (int32_t argc, char* argv[])
{
    CLI_write ("Sensor State: %d\n", gMmwMssMCB.sensorState);
    CLI_write ("LVDS frames streamed: %d\n", gMmwMssMCB.lvdsStream.hwFrameDoneCount);
    return 0;
}

/**
 *  @b Description
 *  @n
 *      This is the CLI Handler for save/restore calibration data to/from flash
 *
 *  @param[in] argc
 *      Number of arguments
 *  @param[in] argv
 *      Arguments
 *
 *  @retval
 *      Success -   0
 *  @retval
 *      Error   -   <0
 */
static int32_t MmwDemo_CLICalibDataSaveRestore(int32_t argc, char* argv[])
{
    if (gMmwMssMCB.sensorState == MmwDemo_SensorState_STARTED)
    {
        CLI_write ("Ignored: This command is not allowed after sensor has started\n");
        return 0;
    }

    if (argc != 4)
    {
        CLI_write ("Error: Invalid usage of the CLI command\n");
        return -1;
    }

    /* Validate inputs */
    if ( ((uint32_t) atoi(argv[1]) == 1) && ((uint32_t) atoi(argv[2] ) == 1))
    {
        CLI_write ("Error: Save and Restore can be enabled only one at a time\n");
        return -1;
    }

    /* Populate configuration: */
    gMmwMssMCB.calibCfg.saveEnable = (uint32_t) atoi(argv[1]);
    gMmwMssMCB.calibCfg.restoreEnable = (uint32_t) atoi(argv[2]);
    sscanf(argv[3], "0x%x", &gMmwMssMCB.calibCfg.flashOffset);

    gMmwMssMCB.isCalibCfgPending = 1;

    return 0;
}

/**
 *  @b Description
 *  @n
 *      This is the CLI Handler for the DDM-MIMO configuration. All TX transmit
 *      on every chirp and TX k is phase-coded into Doppler sub-band k; the last
 *      sub-band stays empty for disambiguation. numBands = 0 disables DDM.
 *
 *  @param[in] argc
 *      Number of arguments
 *  @param[in] argv
 *      Arguments
 *
 *  @retval
 *      Success -   0
 *  @retval
 *      Error   -   <0
 */
static int32_t MmwDemo_CLIDdmCfg (int32_t argc, char* argv[])
{
    uint32_t numBands;

    if (argc != 2)
    {
        CLI_write ("Error: Invalid usage of the CLI command\n");
        return -1;
    }

    if (gMmwMssMCB.sensorState == MmwDemo_SensorState_STARTED)
    {
        CLI_write ("Ignored: This command is not allowed after sensor has started\n");
        return 0;
    }

    /* At least one empty band is needed to disambiguate the TX copies, and the
     * per-chirp phase step must be a whole number of phase shifter LSBs. */
    numBands = (uint32_t) atoi (argv[1]);
    if ((numBands != 0U) &&
        ((numBands <= SYS_COMMON_NUM_TX_ANTENNAS) || (numBands > MMWDEMO_DDM_MAX_BANDS) ||
         ((MMWDEMO_DDM_PHASE_STEPS % numBands) != 0U)))
    {
        CLI_write ("Error: numBands must be 0, or a divisor of 64 in (%d, %d]\n",
                   (int32_t)SYS_COMMON_NUM_TX_ANTENNAS, (int32_t)MMWDEMO_DDM_MAX_BANDS);
        return -1;
    }

    gMmwMssMCB.ddmNumBands = (uint8_t) numBands;
    return 0;
}

/**
 *  @b Description
 *  @n
 *      This is the CLI Execution Task
 *
 *  @retval
 *      Not Applicable.
 */
void MmwDemo_CLIInit (uint8_t taskPriority)
{
    CLI_Cfg     cliCfg;
    char        demoBanner[256];
    uint32_t    cnt;

    /* Create Demo Banner to be printed out by CLI */
    sprintf(&demoBanner[0],
                       "******************************************\n" \
                       "xWR18xx raw-data (DDM) firmware, SDK %02d.%02d.%02d.%02d\n"  \
                       "******************************************\n",
                        MMWAVE_SDK_VERSION_MAJOR,
                        MMWAVE_SDK_VERSION_MINOR,
                        MMWAVE_SDK_VERSION_BUGFIX,
                        MMWAVE_SDK_VERSION_BUILD
            );

    /* Initialize the CLI configuration: */
    memset ((void *)&cliCfg, 0, sizeof(CLI_Cfg));

    /* Populate the CLI configuration: */
    cliCfg.cliPrompt                    = "mmwDemo:/>";
    cliCfg.cliBanner                    = demoBanner;
    cliCfg.cliUartHandle                = gMmwMssMCB.commandUartHandle;
    cliCfg.taskPriority                 = taskPriority;
    cliCfg.socHandle                    = gMmwMssMCB.socHandle;
    cliCfg.mmWaveHandle                 = gMmwMssMCB.ctrlHandle;
    cliCfg.enableMMWaveExtension        = 1U;
    cliCfg.usePolledMode                = true;
    cliCfg.overridePlatform             = true;
    cliCfg.overridePlatformString       = "xWR18xx";

    cnt=0;
    cliCfg.tableEntry[cnt].cmd            = "sensorStart";
    cliCfg.tableEntry[cnt].helpString     = "[doReconfig(optional, default:enabled)]";
    cliCfg.tableEntry[cnt].cmdHandlerFxn  = MmwDemo_CLISensorStart;
    cnt++;

    cliCfg.tableEntry[cnt].cmd            = "sensorStop";
    cliCfg.tableEntry[cnt].helpString     = "No arguments";
    cliCfg.tableEntry[cnt].cmdHandlerFxn  = MmwDemo_CLISensorStop;
    cnt++;

    cliCfg.tableEntry[cnt].cmd            = "adcbufCfg";
    cliCfg.tableEntry[cnt].helpString     = "<subFrameIdx> <adcOutputFmt> <SampleSwap> <ChanInterleave> <ChirpThreshold>";
    cliCfg.tableEntry[cnt].cmdHandlerFxn  = MmwDemo_CLIADCBufCfg;
    cnt++;

    cliCfg.tableEntry[cnt].cmd            = "lvdsStreamCfg";
    cliCfg.tableEntry[cnt].helpString     = "<subFrameIdx> <enableHeader> <dataFmt (1: ADC)> <enableSW (0)>";
    cliCfg.tableEntry[cnt].cmdHandlerFxn  = MmwDemo_CLILvdsStreamCfg;
    cnt++;

    cliCfg.tableEntry[cnt].cmd            = "queryDemoStatus";
    cliCfg.tableEntry[cnt].helpString     = "No arguments";
    cliCfg.tableEntry[cnt].cmdHandlerFxn  = MmwDemo_CLIQueryDemoStatus;
    cnt++;

    cliCfg.tableEntry[cnt].cmd            = "calibData";
    cliCfg.tableEntry[cnt].helpString    = "<save enable> <restore enable> <Flash offset>";
    cliCfg.tableEntry[cnt].cmdHandlerFxn  = MmwDemo_CLICalibDataSaveRestore;
    cnt++;

    cliCfg.tableEntry[cnt].cmd            = "ddmCfg";
    cliCfg.tableEntry[cnt].helpString     = "<numBands (0: disabled)>";
    cliCfg.tableEntry[cnt].cmdHandlerFxn  = MmwDemo_CLIDdmCfg;
    cnt++;

    /* Open the CLI: */
    if (CLI_open (&cliCfg) < 0)
    {
        System_printf ("Error: Unable to open the CLI\n");
        return;
    }
    System_printf ("Debug: CLI is operational\n");
    return;
}
