# SPDX-License-Identifier: MIT
# Host unit test of the RF parser with the DDM chirp checks. Usage: make -C test
SDK      := ../sdk/packages
CFLAGS   := -std=gnu99 -O2 -Wall -Wextra -Werror -D_DEFAULT_SOURCE -I$(SDK)
# MSS build of the RF parser, as in the firmware; TI sources are compiled without -Werror.
MSSFLAGS := -DSOC_XWR18XX -DSUBSYS_MSS \
            -Istubs -I$(SDK)/ti/control/mmwavelink/include
PARSER   := $(SDK)/ti/demo/utils/mmwdemo_rfparser.c

run: rfparser_test
	./rfparser_test

rfparser.o: $(PARSER) $(SDK)/ti/demo/utils/mmwdemo_rfparser.h
	$(CC) -std=gnu99 -O2 -w -I$(SDK) $(MSSFLAGS) -c $< -o $@

rfparser_test: rfparser_test.c rfparser.o
	$(CC) $(CFLAGS) -Wno-unused-parameter $(MSSFLAGS) $^ -lm -o $@

clean:
	rm -f rfparser_test rfparser.o

.PHONY: run clean
