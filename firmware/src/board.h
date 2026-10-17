/* board.h -- hand-written board support header with calgen-managed blocks.
 *
 * SYNTHETIC DEMO: written for the calgen demo; not from any real product or
 * vendor SDK.
 *
 * This file shows "patch mode": everything outside the CALGEN markers is
 * maintained by hand; everything inside is rewritten by
 *     calgen build specs/variants/fa10507.yaml --patch firmware/src/board.h
 * Do not edit between the markers.
 */
#ifndef BOARD_H
#define BOARD_H

#include "calgen_types.h"

/* Hand-maintained: GPIO and peripheral assignments (not calibration). */
#define BOARD_LED_FAULT_GPIO   31
#define BOARD_RELAY_BYPASS_GPIO 12

/* CALGEN:BEGIN bus */
/* DC bus regulation setpoint, bus minimum plus design margin, rounded up to 10 V
 * = ceil(vbus_min * (1 + design.vbus_margin) / 10) * 10
 *   design.vbus_margin = 7 %  [design fa10507.yaml] */
#define UPS_VBUS_SET_V             410.0f         /* 410 V */

/* Bus voltage at ADC full scale (divider ratio times ADC reference)
 * = target.v_ref * (board.vbus_r_top + board.vbus_r_bot) / board.vbus_r_bot
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.vbus_r_top = 1.5 Mohm  [board ups_ctrl_revA.yaml]
 *   board.vbus_r_bot = 10 kohm  [board ups_ctrl_revA.yaml] */
#define UPS_VBUS_FS_V              498.3f         /* 498.3 V */

/* Volts of bus per ADC count
 * = vbus_fs / target.adc_div
 *   target.adc_div = 4096 counts  [target f28004x.yaml] */
#define UPS_VBUS_V_PER_COUNT       0.12165527f    /* 0.121655 V/count */
/* CALGEN:END bus */

/* CALGEN:BEGIN out */
/* Rated output current (RMS)
 * = ds.power_va / ds.vout_nom
 *   ds.power_va = 1500 VA  [DS-10507 Rev.101119 p2: "1500 VA, 1250 W"]
 *   ds.vout_nom = 120 V  [DS-10507 Rev.101119 p2: "120VAC, (+/-3%) Selectable (Optional 240VAC Output)"] */
#define UPS_IOUT_RATED_A           12.5f          /* 12.5 A */

/* Overload alarm current (RMS)
 * = iout_rated * ds.overload_alarm_pct
 *   NOT GENERATED: input ds.overload_alarm_pct not in data sheet */

/* Software overload trip level (RMS, timed; acts after UPS_OVERLOAD_DELAY_MS above this level)
 * = iout_rated * ds.overload_trip_pct
 *   ds.overload_trip_pct = 120 %  [DS-10507 Rev.101119 p2 (read as 120% of rated): "Shutdown at 20% Overload"] */
#define UPS_IOUT_TRIP_A            15.0f          /* 15 A */

/* Time above the RMS trip level before the overload action (the data sheet gives no time)
 * = design.overload_delay
 *   design.overload_delay = 30 s  [design fa10507.yaml] */
#define UPS_OVERLOAD_DELAY_MS      30000u         /* 30000 ms, uint32 */

/* Hardware peak-current limit (fast comparator, short-circuit protection); must clear the crest factor of rated nonlinear loads
 * = design.pk_limit_factor * iout_rated
 *   design.pk_limit_factor = 3.5  [design fa10507.yaml] */
#define UPS_IOUT_PK_LIMIT_A        43.75f         /* 43.75 A */

/* Peak current at the edge of the mid-rail-biased current-sense range
 * = target.v_ref / 2 / (board.r_shunt * board.g_amp)
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.r_shunt = 2 mohm  [board ups_ctrl_revA.yaml]
 *   board.g_amp = 10  [board ups_ctrl_revA.yaml] */
#define UPS_IOUT_FS_PK_A           82.5f          /* 82.5 A */

/* Comparator DAC code for the positive hardware peak-current limit
 * = floor((target.v_ref / 2 + iout_pk_limit * board.r_shunt * board.g_amp) / target.v_ref * target.dac_div)
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.r_shunt = 2 mohm  [board ups_ctrl_revA.yaml]
 *   board.g_amp = 10  [board ups_ctrl_revA.yaml]
 *   target.dac_div = 4096 counts  [target f28004x.yaml] */
#define UPS_IOUT_PKLIM_DAC_HI      3134u          /* 3134 counts, uint16 */

/* Comparator DAC code for the negative hardware peak-current limit
 * = ceil((target.v_ref / 2 - iout_pk_limit * board.r_shunt * board.g_amp) / target.v_ref * target.dac_div)
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.r_shunt = 2 mohm  [board ups_ctrl_revA.yaml]
 *   board.g_amp = 10  [board ups_ctrl_revA.yaml]
 *   target.dac_div = 4096 counts  [target f28004x.yaml] */
#define UPS_IOUT_PKLIM_DAC_LO      962u           /* 962 counts, uint16 */

/* What the unit does when the RMS overload persists past the delay
 * = ds.overload_action
 *   ds.overload_action = shutdown  [DS-10507 Rev.101119 p2: "Shutdown at 20% Overload"] */
#define UPS_OVERLOAD_ACTION        UPS_OL_SHUTDOWN
/* CALGEN:END out */

#endif /* BOARD_H */
