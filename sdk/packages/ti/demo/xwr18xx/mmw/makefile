###################################################################################
# mmWave Demo Level makefile
###################################################################################
ifeq ($(CCS_MAKEFILE_BASED_BUILD), 1)
ifeq ($(OS),Windows_NT)
include $(MMWAVE_SDK_INSTALL_PATH)/scripts/windows/setenv.mak
else
include $(MMWAVE_SDK_INSTALL_PATH)/scripts/unix/setenv.mak
endif
endif


include $(MMWAVE_SDK_INSTALL_PATH)/ti/common/mmwave_sdk.mak
include ./mss/mmw_mss.mak

MMW_DEMO_BIN         = $(MMWAVE_SDK_DEVICE_TYPE)_mmw_demo.bin

.PHONY: all clean
.NOTPARALLEL:

# Raw-data firmware: MSS and radar subsystem only; the DSP image is left out (NULL)
# and the DSP stays halted.
mmwDemo: mssDemo
	@$(GENERATE_METAIMAGE) $(MMW_DEMO_BIN) $(SHMEM_ALLOC) $(MSS_MMW_DEMO_OUT) $(XWR18XX_RADARSS_IMAGE_BIN) NULL

# Clean: This cleans all the objects
clean: mssDemoClean
	@$(DEL) $(MMW_DEMO_BIN)

# This builds all the supported demos
all: mmwDemo

# Help: This displays the MAKEFILE Usage.
help:
	@echo '****************************************************************************************'
	@echo '* Makefile Targets for the DEMO '
	@echo 'all	       -> Builds the raw-data firmware image (MSS only)'
	@echo 'clean           -> Cleans the firmware image'
	@echo 'mssDemo         -> Builds the MSS binary'
	@echo 'mssDemoClean    -> Cleans the MSS binary'
	@echo '****************************************************************************************'
