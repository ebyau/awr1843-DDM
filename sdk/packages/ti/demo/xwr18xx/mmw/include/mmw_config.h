/**
 *   @file  mmw_config.h
 *
 *   @brief
 *      Configuration types of the raw-data firmware: the sensor, the LVDS raw
 *      data stream and the platform.
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
#ifndef MMW_CONFIG_H
#define MMW_CONFIG_H

#include <ti/control/mmwave/mmwave.h>
#include <ti/common/sys_common.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief
 *  LVDS streaming configuration (lvdsStreamCfg). Only raw ADC samples are streamed,
 *  through the CBUFF hardware session.
 */
typedef struct MmwDemo_LvdsStreamCfg_t
{
    /*! @brief  HSI header enabled/disabled flag */
    bool        isHeaderEnabled;

/*! @brief  ADC samples of every chirp */
#define MMW_DEMO_LVDS_STREAM_CFG_DATAFMT_ADC        1

    /*! @brief  Data format of the HW session: one of MMW_DEMO_LVDS_STREAM_CFG_DATAFMT_* */
    uint8_t     dataFmt;
} MmwDemo_LvdsStreamCfg;

/**
 * @brief
 *  Platform specific configuration
 */
typedef struct MmwDemo_platformCfg_t
{
    /*! @brief   GPIO index for sensor status */
    uint32_t            SensorStatusGPIO;

    /*! @brief   CPU Clock Frequency. */
    uint32_t            sysClockFrequency;

    /*! @brief   UART Command Baud Rate. */
    uint32_t            commandBaudRate;
} MmwDemo_platformCfg;

/**
 * @brief
 *  Sensor configuration
 */
typedef struct MmwDemo_Cfg_t
{
    /*! @brief   mmWave Control Configuration. */
    MMWave_CtrlCfg      ctrlCfg;

    /*! @brief   mmWave Open Configuration. */
    MMWave_OpenCfg      openCfg;

    /*! @brief   Platform specific configuration. */
    MmwDemo_platformCfg platformCfg;
} MmwDemo_Cfg;

#ifdef __cplusplus
}
#endif

#endif /* MMW_CONFIG_H */
