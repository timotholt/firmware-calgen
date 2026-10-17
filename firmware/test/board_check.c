/* board_check.c -- proves the patch-mode board.h compiles and carries real values.
 * SYNTHETIC DEMO: written for the calgen demo. */
#include <stdio.h>

#include "board.h"

int main(void)
{
    if ((unsigned)UPS_IOUT_PKLIM_DAC_HI != 3134u || (unsigned)BOARD_LED_FAULT_GPIO != 31u) {
        printf("FAIL board.h values\n");
        return 1;
    }
    printf("board.h patch-mode check passed\n");
    return 0;
}
