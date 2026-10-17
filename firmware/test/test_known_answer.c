/* test_known_answer.c -- compiled once per variant; asserts generated constants
 * and the code that consumes them against values worked out by hand from the
 * formulas in specs/rules.yaml (see tests/test_build.py for the arithmetic).
 *
 * SYNTHETIC DEMO: written for the calgen demo.
 */
#include <math.h>
#include <stdio.h>

#include "ups_ctrl.h"
#include CALGEN_HEADER

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
    EXPECT_INT(trip.hi, 3364);
    EXPECT_INT(trip.lo, 731);
    EXPECT_INT(pwm.period, 5000);
    EXPECT_INT(pwm.deadband, 30);
    EXPECT_INT(ups_fout_mode(), UPS_FOUT_CHANGER);
    EXPECT_INT(ups_overload_action(), UPS_OL_SHUTDOWN);
#ifdef UPS_IOUT_ALARM_A
    printf("FAIL FA10507 data sheet has no alarm level, but UPS_IOUT_ALARM_A is defined\n");
    failures++;
#endif
    EXPECT_INT(ups_overload_state(14.9f), UPS_OL_NORMAL);
    EXPECT_INT(ups_overload_state(15.0f), UPS_OL_TRIP);
    EXPECT_NEAR(ups_vbus_volts(3370), 410.08, 0.01);
    EXPECT_INT(ups_vout_in_band(120.0f), 1);
    EXPECT_INT(ups_vout_in_band(124.0f), 0);
    EXPECT_INT(ups_battery_low(69.8f), 1);
    EXPECT_INT(ups_battery_low(70.0f), 0);

#elif defined(KA_FA10449)
    EXPECT_NEAR(CALGEN_REAL(UPS_IOUT_ALARM_A), 5.6875, 1e-5);
    EXPECT_NEAR(CALGEN_REAL(UPS_IOUT_TRIP_A), 6.229167, 1e-5);
    EXPECT_INT(trip.hi, 2594);
    EXPECT_INT(trip.lo, 1501);
    EXPECT_INT(ups_fout_mode(), UPS_FOUT_FOLLOWER);
    EXPECT_INT(ups_overload_state(5.5f), UPS_OL_NORMAL);
    EXPECT_INT(ups_overload_state(5.7f), UPS_OL_ALARM);
    EXPECT_INT(ups_overload_state(6.3f), UPS_OL_TRIP);

#elif defined(KA_FA10434)
    EXPECT_NEAR(CALGEN_REAL(UPS_IIN_LIMIT_A), 7.4, 1e-6);
    EXPECT_INT(trip.hi, 2720);
    EXPECT_INT(trip.lo, 1375);
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
    EXPECT_INT(trip.hi, 840);
    EXPECT_INT(trip.lo, 183);
    EXPECT_INT(pwm.period, 3000);
    EXPECT_INT(pwm.deadband, 18);
    EXPECT_INT(ups_overload_state(15.0f), UPS_OL_TRIP);

#else
#error "define one KA_<VARIANT> to select the expected values"
#endif

    if (failures == 0) {
        printf("known-answer test passed: %s\n", CALGEN_HEADER);
    }
    return failures == 0 ? 0 : 1;
}
