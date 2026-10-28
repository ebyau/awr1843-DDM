# SPDX-License-Identifier: MIT
# Host unit tests for hardware-independent DDM code. Usage: make -C test
SDK      := ../sdk/packages
CFLAGS   := -std=gnu99 -O2 -Wall -Wextra -Werror -D_DEFAULT_SOURCE -I$(SDK)
# AWR1843AOP build of the demo RF parser; TI sources are compiled without -Werror.
AOPFLAGS := -DSOC_XWR18XX -DSUBSYS_MSS -DUSE_2D_AOA_DPU -DXWR18XX_AOP_ANTENNA_PATTERN \
            -Istubs -I$(SDK)/ti/control/mmwavelink/include
PARSER   := $(SDK)/ti/demo/utils/mmwdemo_rfparser.c

run: ddm_test rfparser_test
	./ddm_test
	./rfparser_test

ddm_test: ddm_test.c $(SDK)/ti/datapath/dpif/dpif_ddm.h
	$(CC) $(CFLAGS) $< -lm -o $@

rfparser.o: $(PARSER) $(SDK)/ti/demo/utils/mmwdemo_rfparser.h
	$(CC) -std=gnu99 -O2 -w -I$(SDK) $(AOPFLAGS) -c $< -o $@

rfparser_test: rfparser_test.c rfparser.o
	$(CC) $(CFLAGS) -Wno-unused-parameter $(AOPFLAGS) $^ -lm -o $@

clean:
	rm -f ddm_test rfparser_test rfparser.o

.PHONY: run clean
