/**
 *   @file  mmw_mss.h
 *
 *   @brief
 *      Main header of the raw-data firmware: the sensor streams raw ADC samples
 *      over LVDS and does no signal processing on the device.
 *
 *  \par
 *  NOTE:
 *      (C) Copyright 2016 Texas Instruments, Inc.
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
#ifndef MMW_MSS_H
#define MMW_MSS_H

#include <ti/sysbios/knl/Semaphore.h>
#include <ti/sysbios/knl/Task.h>

#include <ti/common/mmwave_error.h>
#include <ti/drivers/osal/DebugP.h>
#include <ti/drivers/soc/soc.h>
#include <ti/drivers/uart/UART.h>
#include <ti/drivers/gpio/gpio.h>
#include <ti/drivers/edma/edma.h>
#include <ti/demo/utils/mmwdemo_adcconfig.h>
#include <ti/demo/xwr18xx/mmw/include/mmw_config.h>
#include <ti/demo/xwr18xx/mmw/mss/mmw_lvds_stream.h>

#ifdef __cplusplus
extern "C" {
#endif

/*! @brief Phase shifter resolution: 6 bits, 1 LSB = 360/64 degrees. */
#define MMWDEMO_DDM_PHASE_STEPS     64U

/*! @brief Largest number of DDM Doppler sub-bands (one chirp definition each). */
#define MMWDEMO_DDM_MAX_BANDS       16U

/**
 * @brief
 *  Sensor state
 */
typedef enum MmwDemo_SensorState_e
{
    /*! @brief Inital state after sensor is initialized. */
    MmwDemo_SensorState_INIT = 0,

    /*! @brief Inital state after sensor is post RF init. */
    MmwDemo_SensorState_OPENED,

    /*! @brief Indicates sensor is started */
    MmwDemo_SensorState_STARTED,

    /*! @brief  State after sensor has completely stopped */
    MmwDemo_SensorState_STOPPED
}MmwDemo_SensorState;

/**
 * @brief
 *  Counters of the asynchronous events from the radar subsystem (BSS)
 */
typedef struct MmwDemo_MSS_Stats_t
{
    /*! @brief   Counter which tracks the number of frame trigger events from BSS */
    uint64_t     frameTriggerReady;

    /*! @brief   Counter which tracks the number of failed calibration reports */
    uint32_t     failedTimingReports;

    /*! @brief   Counter which tracks the number of calibration reports received */
    uint32_t     calibrationReports;

    /*! @brief   Counter which tracks the number of sensor stops (frame end events) */
    uint32_t     sensorStopped;
}MmwDemo_MSS_Stats;

/**
 * @brief
 *  Task handles
 */
typedef struct MmwDemo_TaskHandles_t
{
    /*! @brief   mmWave control task handle */
    Task_Handle mmwaveCtrl;

    /*! @brief   Init task handle */
    Task_Handle initTask;
} MmwDemo_taskHandles;

typedef struct MmwDemo_calibDataHeader_t
{
    /*! @brief      Magic word for calibration data header */
    uint32_t 	magic;

    /*! @brief      Header length */
    uint32_t 	hdrLen;

    /*! @brief      mmwLink version */
    rlSwVersionParam_t 	linkVer;

    /*! @brief      RadarSS version */
    rlFwVersionParam_t 	radarSSVer;

    /*! @brief      Data length */
    uint32_t 	dataLen;

    /*! @brief      data padding to make sure calib data is 8 bytes aligned */
    uint32_t      padding;
} MmwDemo_calibDataHeader;

/*!
 * @brief
 * Structure holds calibration save configuration used during sensor open.
 *
 * @details
 *  The structure holds calibration save configuration.
 */
typedef struct MmwDemo_calibCfg_t
{
    /*! @brief      Calibration data header for validation read from flash */
    MmwDemo_calibDataHeader    calibDataHdr;

    /*! @brief      Size of Calibraton data size includng header */
    uint32_t 		sizeOfCalibDataStorage;

    /*! @brief      Enable/Disable calibration save process  */
    uint32_t 		saveEnable;

    /*! @brief      Enable/Disable calibration restore process  */
    uint32_t 		restoreEnable;
	
    /*! @brief      Flash Offset to restore the data from */
    uint32_t 		flashOffset;
} MmwDemo_calibCfg;


/*!
 * @brief
 * Structure holds calibration restore configuration used during sensor open.
 *
 * @details
 *  The structure holds calibration restore configuration.
 */
typedef struct MmwDemo_calibData_t
{
    /*! @brief      Calibration data header for validation read from flash */
    MmwDemo_calibDataHeader    calibDataHdr;

    /*! @brief      Calibration data */
    rlCalibrationData_t               calibData;

    /*! @brief      Phase shift Calibration data */
    rlPhShiftCalibrationData_t     phaseShiftCalibData;

    /* Future: If more fields are added to this structure or RL definitions
        are changed, please add dummy padding bytes here if size of
        MmwDemo_calibData is not multiple of 8 bytes. */
} MmwDemo_calibData;

/**
 * @brief
 *  Millimeter Wave Demo MCB
 */
typedef struct MmwDemo_MSS_MCB_t
{
    /*! @brief      Configuration which is used to execute the demo */
    MmwDemo_Cfg                 cfg;

    /*! * @brief    Handle to the SOC Module */
    SOC_Handle                  socHandle;

    /*! @brief      UART Command Rx/Tx Handle */
    UART_Handle                 commandUartHandle;

    /*! @brief      This is the mmWave control handle which is used
     * to configure the BSS. */
    MMWave_Handle               ctrlHandle;

    /*! @brief      ADCBuf driver handle */
    ADCBuf_Handle               adcBufHandle;

    /*! @brief   Handle of the EDMA driver, used for CBUFF */
    EDMA_Handle                 edmaHandle;

    /*! @brief   Number of EDMA event Queues (tc) */
    uint8_t                     numEdmaEventQueues;

    /*! @brief   True if need to poll for edma error (because error interrupt is not
     *           connected to the CPU on the device */
    bool                        isPollEdmaError;

    /*! @brief   True if need to poll for edma transfer controller error
     *           because at least one of the transfer controller error interrupts
     *           are not connected to the CPU on the device */
    bool                        isPollEdmaTransferControllerError;

    /*! @brief   EDMA error Information when there are errors like missing events */
    EDMA_errorInfo_t            EDMA_errorInfo;

    /*! @brief EDMA transfer controller error information. */
    EDMA_transferControllerErrorInfo_t EDMA_transferControllerErrorInfo;

    /*! @brief      ADC buffer configuration (adcbufCfg) */
    MmwDemo_ADCBufCfg           adcBufCfg;

    /*! @brief      LVDS raw data stream configuration (lvdsStreamCfg) */
    MmwDemo_LvdsStreamCfg       lvdsStreamCfg;

    /*! @brief      ADC samples per chirp, from the profile */
    uint16_t                    numAdcSamples;

    /*! @brief      Chirps per frame, from the frame configuration */
    uint16_t                    numChirpsPerFrame;

    /*! @brief      Demo Stats */
    MmwDemo_MSS_Stats           stats;

    /*! @brief      Task handle storage */
    MmwDemo_taskHandles         taskHandles;

    /*! @brief   Rf frequency scale factor, = 2.7 for 60GHz device, = 3.6 for 76GHz device */
    double                      rfFreqScaleFactor;

    /*! @brief   Semaphore handle to signal the frame end after MMWave_stop */
    Semaphore_Handle            frameEndSemHandle;

    /*! @brief    Sensor state */
    MmwDemo_SensorState         sensorState;

    /*! @brief   Tracks the number of sensor start */
    uint32_t                    sensorStartCount;

    /*! @brief   Tracks the number of sensor sop */
    uint32_t                    sensorStopCount;

    /*! @brief   this structure is used to hold all the relevant information
         for the mmw demo LVDS stream*/
    MmwDemo_LVDSStream_MCB_t    lvdsStream;

    /*! @brief   Calibration cofiguration for save/restore */
    MmwDemo_calibCfg            calibCfg;

    /*! @brief Flag indicating if @ref adcBufCfg is pending processing. */
    uint8_t isAdcBufCfgPending : 1;

    /*! @brief Flag indicating if @ref lvdsStreamCfg is pending processing. */
    uint8_t isLvdsStreamCfgPending : 1;

    /*! @brief Flag indicating if @ref calibCfg is pending processing. */
    uint8_t isCalibCfgPending : 1;

    /*! @brief Number of Doppler sub-bands for DDM-MIMO; 0 disables DDM (stock TDM). */
    uint8_t ddmNumBands;

    /*! @brief True while the per-chirp TX phase shifters are enabled in the RF front end. */
    bool isDdmPhaseShifterEnabled;
} MmwDemo_MSS_MCB;

/**************************************************************************
 *************************** Extern Definitions ***************************
 **************************************************************************/
extern int32_t MmwDemo_openSensor(bool isFirstTimeOpen);
extern int32_t MmwDemo_configSensor(void);
extern int32_t MmwDemo_startSensor(void);
extern void MmwDemo_stopSensor(void);

/* Debug Functions */
extern void _MmwDemo_debugAssert(int32_t expression, const char *file, int32_t line);
#define MmwDemo_debugAssert(expression) {                                      \
                                         _MmwDemo_debugAssert(expression,      \
                                                  __FILE__, __LINE__);         \
                                         DebugP_assert(expression);             \
                                        }

#ifdef __cplusplus
}
#endif

#endif /* MMW_MSS_H */
