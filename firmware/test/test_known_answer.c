/* test_known_answer.c -- compiled once per variant; asserts generated constants
 * and the code that consumes them against values worked out by hand from the
 * formulas in specs/rules.yaml (see tests/test_build.py for the arithmetic).
 *
 * SYNTHETIC DEMO: written for the calgen demo.
 */
#include <math.h>
#include <stdio.h>

#include "ups_ctrl.h" /* includes CALGEN_HEADER */

static int failures = 0;

#define EXPECT_INT(actual, expected)                                                    \
    do {                                                                                \
        long a_ = (long)(actual), e_ = (long)(expected);                                \
        if (a_ != e_) {                                                                 \
            printf("FAIL %s:%d %s = %ld, expected %ld\n", __FILE__, __LINE__, #actual, a_, e_); \
            failures++;                                                                 \
        }                                                                               \
    } while (0)

#define EXPECT_NEAR(actual, expected, tol)                                              \
    do {                                                                                \
        double a_ = (double)(actual), e_ = (double)(expected);                          \
        if (fabs(a_ - e_) > (tol)) {                                                    \
            printf("FAIL %s:%d %s = %.7g, expected %.7g\n", __FILE__, __LINE__, #actual, a_, e_); \
            failures++;                                                                 \
        }                                                                               \
    } while (0)

int main(void)
{
    ups_pwm_cfg_t pwm = ups_pwm_config();
    ups_trip_cfg_t trip = ups_trip_config();
    (void)pwm; /* not every variant checks every field */

#if defined(KA_FA10507)
    EXPECT_NEAR(CALGEN_REAL(UPS_IOUT_RATED_A), 12.5, 1e-6);
    EXPECT_NEAR(CALGEN_REAL(UPS_IOUT_TRIP_A), 15.0, 1e-6);
    EXPECT_NEAR(CALGEN_REAL(UPS_VBUS_SET_V), 410.0, 1e-4);
    EXPECT_NEAR(CALGEN_REAL(UPS_IOUT_PK_LIMIT_A), 43.75, 1e-5);  /* 3.5 x 12.5 A */
    EXPECT_INT(trip.hi, 3134);   /* (1.65 + 43.75 * 0.02) / 3.3 * 4096 = 3134.06, floor */
    EXPECT_INT(trip.lo, 962);    /* (1.65 - 0.875) / 3.3 * 4096 = 961.94, ceil */
    EXPECT_INT(pwm.period, 2500);  /* 100 MHz / (2 * 20 kHz), up-down count */
    EXPECT_INT(pwm.deadband, 100); /* 1 us * 100 MHz */
    EXPECT_INT(UPS_OVERLOAD_DELAY_MS, 30000);
    {
        uint32_t over = 0;
        EXPECT_INT(ups_overload_update(15.0f, 29000, &over), UPS_OL_ALARM); /* above trip, not yet long enough */
        EXPECT_INT(ups_overload_update(15.0f, 1000, &over), UPS_OL_TRIP);   /* 30 s reached */
        EXPECT_INT(ups_overload_update(10.0f, 10, &over), UPS_OL_NORMAL);  /* back below: timer resets */
        EXPECT_INT(over, 0);
    }
    EXPECT_INT(ups_fout_mode(), UPS_FOUT_CHANGER);
    EXPECT_INT(ups_overload_action(), UPS_OL_SHUTDOWN);
#ifdef UPS_IOUT_ALARM_A
    printf("FAIL FA10507 data sheet has no alarm level, but UPS_IOUT_ALARM_A is defined\n");
    failures++;
#endif
    EXPECT_INT(ups_overload_state(14.9f), UPS_OL_NORMAL);
    EXPECT_INT(ups_overload_state(15.0f), UPS_OL_TRIP);
    EXPECT_NEAR(ups_vbus_volts(3370), 409.98, 0.01);  /* 3370 * 498.3 V / 4096 */
    EXPECT_INT(ups_vout_in_band(120.0f), 1);
    EXPECT_INT(ups_vout_in_band(124.0f), 0);
    EXPECT_INT(ups_battery_low(70.0f), 1);   /* 28 cells x 2.5 V */
    EXPECT_INT(ups_battery_low(70.1f), 0);

#elif defined(KA_FA10449)
    EXPECT_NEAR(CALGEN_REAL(UPS_IOUT_ALARM_A), 5.6875, 1e-5);
    EXPECT_NEAR(CALGEN_REAL(UPS_IOUT_TRIP_A), 6.229167, 1e-5);
    EXPECT_INT(trip.hi, 2518);   /* 3.5 x 5.4167 A = 18.958 A peak limit */
    EXPECT_INT(trip.lo, 1578);   /* (1.65 - 0.3792) / 3.3 * 4096 = 1577.37, ceil */
    EXPECT_INT(ups_fout_mode(), UPS_FOUT_FOLLOWER);
    EXPECT_INT(ups_overload_state(5.5f), UPS_OL_NORMAL);
    EXPECT_INT(ups_overload_state(5.7f), UPS_OL_ALARM);
    EXPECT_INT(ups_overload_state(6.3f), UPS_OL_TRIP);

#elif defined(KA_FA10434)
    EXPECT_NEAR(CALGEN_REAL(UPS_IIN_LIMIT_A), 7.4, 1e-6);
    EXPECT_INT(trip.hi, 2627);   /* 3.5 x 6.6667 A = 23.33 A peak limit */
    EXPECT_INT(trip.lo, 1469);   /* 1468.77, ceil */
    EXPECT_INT(ups_overload_action(), UPS_OL_BYPASS);
    EXPECT_NEAR(CALGEN_REAL(UPS_VBAT_NOM_V), 36.0, 1e-6);

#elif defined(KA_FA10507_F2803X)
#ifndef CALGEN_GLOBAL_Q
    printf("FAIL legacy target header should define CALGEN_GLOBAL_Q\n");
    failures++;
#else
    EXPECT_INT(CALGEN_GLOBAL_Q, 20);
#endif
    EXPECT_INT(UPS_IOUT_TRIP_A, 15L << 20);
    EXPECT_NEAR(CALGEN_REAL(UPS_IOUT_TRIP_A), 15.0, 1e-6);
    EXPECT_INT(trip.hi, 782);    /* 10-bit DAC: 2.525 / 3.3 * 1023 = 782.75, floor */
    EXPECT_INT(trip.lo, 241);    /* 0.775 / 3.3 * 1023 = 240.25, ceil */
    EXPECT_INT(pwm.period, 1500);  /* 60 MHz / (2 * 20 kHz) */
    EXPECT_INT(pwm.deadband, 60);  /* 1 us * 60 MHz */
    /* fixed-point build: calgen_num_t is an integer, so the comparisons below run in IQ20 */
    EXPECT_INT((calgen_num_t)0.5, 0);
    EXPECT_INT(sizeof(calgen_num_t), 4);
    EXPECT_INT(ups_overload_state(CALGEN_NUM(14.9)), UPS_OL_NORMAL);
    EXPECT_INT(ups_overload_state(CALGEN_NUM(15.0)), UPS_OL_TRIP);
    EXPECT_INT(ups_vbus_volts(4095), 4095L * UPS_VBUS_V_PER_COUNT); /* full scale: no int32 overflow */
    EXPECT_NEAR(CALGEN_REAL(ups_vbus_volts(3370)), 409.98, 0.01);
    EXPECT_INT(ups_battery_low(CALGEN_NUM(70.0)), 1);
    EXPECT_INT(ups_battery_low(CALGEN_NUM(70.1)), 0);

#else
#error "define one KA_<VARIANT> to select the expected values"
#endif

    if (failures == 0) {
        printf("known-answer test passed: %s\n", CALGEN_HEADER);
    }
    return failures == 0 ? 0 : 1;
}
