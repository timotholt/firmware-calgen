# Sample firmware build: a host-compiler stand-in for TI Code Composer Studio.
# It proves the generated headers are valid C99 under strict warnings and that
# the values match hand-worked answers. It does NOT prove anything about a real
# C2000 build (16-bit char/int, cl2000 diagnostics, linker maps).

CC      ?= cc
CFLAGS  ?= -std=c99 -Wall -Wextra -Werror -pedantic -O1
BUILD   := build
INC     := -Iinclude -Isrc

# variant -> known-answer selector
VARIANTS := fa10449 fa10434 fa10507 fa10507_f2803x
KA_fa10449        := KA_FA10449
KA_fa10434        := KA_FA10434
KA_fa10507        := KA_FA10507
KA_fa10507_f2803x := KA_FA10507_F2803X

BINS := $(addprefix $(BUILD)/ka_,$(VARIANTS)) $(BUILD)/board_check

.PHONY: all test clean
all: $(BINS)

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/ka_%: src/ups_ctrl.c test/test_known_answer.c include/calgen_%.h include/calgen_types.h | $(BUILD)
	$(CC) $(CFLAGS) $(INC) -DCALGEN_HEADER='"calgen_$*.h"' -D$(KA_$*) \
		src/ups_ctrl.c test/test_known_answer.c -lm -o $@

$(BUILD)/board_check: test/board_check.c src/board.h include/calgen_types.h | $(BUILD)
	$(CC) $(CFLAGS) $(INC) test/board_check.c -o $@

test: all
	@set -e; for b in $(BINS); do ./$$b; done

clean:
	rm -rf $(BUILD)
