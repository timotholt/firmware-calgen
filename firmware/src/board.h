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
 * = vbus_fs / target.adc_max
 *   target.adc_max = 4095 counts  [target f28004x.yaml] */
#define UPS_VBUS_V_PER_COUNT       0.121684976f   /* 0.121685 V */
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

/* Overload trip current (RMS)
 * = iout_rated * ds.overload_trip_pct
 *   ds.overload_trip_pct = 120 %  [DS-10507 Rev.101119 p2 (read as 120% of rated): "Shutdown at 20% Overload"] */
#define UPS_IOUT_TRIP_A            15.0f          /* 15 A */

/* Instantaneous current at the RMS trip level (sine), what a hardware comparator sees
 * = sqrt(2) * iout_trip */
#define UPS_IOUT_TRIP_PK_A         21.213203f     /* 21.2132 A */

/* Peak current at the edge of the mid-rail-biased current-sense range
 * = target.v_ref / 2 / (board.r_shunt * board.g_amp)
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.r_shunt = 5 mohm  [board ups_ctrl_revA.yaml]
 *   board.g_amp = 10 ratio  [board ups_ctrl_revA.yaml] */
#define UPS_IOUT_FS_PK_A           33.0f          /* 33 A */

/* Comparator DAC code for the positive overcurrent trip
 * = round((target.v_ref / 2 + iout_trip_pk * board.r_shunt * board.g_amp) / target.v_ref * target.dac_max)
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.r_shunt = 5 mohm  [board ups_ctrl_revA.yaml]
 *   board.g_amp = 10 ratio  [board ups_ctrl_revA.yaml]
 *   target.dac_max = 4095 counts  [target f28004x.yaml] */
#define UPS_IOUT_TRIP_DAC_HI       3364u          /* 3364 counts, uint16 */

/* Comparator DAC code for the negative overcurrent trip
 * = round((target.v_ref / 2 - iout_trip_pk * board.r_shunt * board.g_amp) / target.v_ref * target.dac_max)
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.r_shunt = 5 mohm  [board ups_ctrl_revA.yaml]
 *   board.g_amp = 10 ratio  [board ups_ctrl_revA.yaml]
 *   target.dac_max = 4095 counts  [target f28004x.yaml] */
#define UPS_IOUT_TRIP_DAC_LO       731u           /* 731 counts, uint16 */

/* What the unit does when the trip level is exceeded
 * = ds.overload_action
 *   ds.overload_action = shutdown  [DS-10507 Rev.101119 p2: "Shutdown at 20% Overload"] */
#define UPS_OVERLOAD_ACTION        UPS_OL_SHUTDOWN
/* CALGEN:END out */

#endif /* BOARD_H */
