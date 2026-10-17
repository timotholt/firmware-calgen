/* ups_ctrl.c -- tiny fake UPS controller: consumes generated constants.
 *
 * SYNTHETIC DEMO: written for the calgen demo; not from any real product or
 * vendor SDK.
 *
 * Build with -DCALGEN_HEADER='"calgen_<variant>.h"' to select a variant.
 * CALGEN_REAL() converts IQ integers to float on fixed-point targets and is a
 * no-op on float targets, so one source file serves both.
 */
#include "ups_ctrl.h"

#ifndef CALGEN_HEADER
#error "define CALGEN_HEADER, e.g. -DCALGEN_HEADER='\"calgen_fa10507.h\"'"
#endif
#include CALGEN_HEADER

float ups_vbus_volts(uint16_t adc_counts)
{
    return (float)adc_counts * CALGEN_REAL(UPS_VBUS_V_PER_COUNT);
}

ups_ol_state_t ups_overload_state(float iout_rms)
{
    if (iout_rms >= CALGEN_REAL(UPS_IOUT_TRIP_A)) {
        return UPS_OL_TRIP;
    }
#ifdef UPS_IOUT_ALARM_A
    if (iout_rms >= CALGEN_REAL(UPS_IOUT_ALARM_A)) {
        return UPS_OL_ALARM;
    }
#endif /* not every data sheet defines an alarm level */
    return UPS_OL_NORMAL;
}

/* Software overload: RMS current above the trip level for longer than
 * UPS_OVERLOAD_DELAY_MS triggers the overload action. The hardware peak-current
 * limit (comparator, see ups_trip_config) is separate and much faster. */
ups_ol_state_t ups_overload_update(float iout_rms, uint32_t dt_ms, uint32_t *over_ms)
{
    if (iout_rms >= CALGEN_REAL(UPS_IOUT_TRIP_A)) {
        *over_ms += dt_ms;
        return *over_ms >= (uint32_t)UPS_OVERLOAD_DELAY_MS ? UPS_OL_TRIP : UPS_OL_ALARM;
    }
    *over_ms = 0u;
    return ups_overload_state(iout_rms) == UPS_OL_ALARM ? UPS_OL_ALARM : UPS_OL_NORMAL;
}

int ups_vout_in_band(float vout_rms)
{
    return vout_rms >= CALGEN_REAL(UPS_VOUT_LO_V) && vout_rms <= CALGEN_REAL(UPS_VOUT_HI_V);
}

int ups_battery_low(float vbat)
{
    return vbat <= CALGEN_REAL(UPS_VBAT_CUTOFF_V);
}

ups_pwm_cfg_t ups_pwm_config(void)
{
    ups_pwm_cfg_t cfg;
    cfg.period = (uint16_t)UPS_PWM_PERIOD_CNT;
    cfg.deadband = (uint16_t)UPS_PWM_DEADBAND_CNT;
    return cfg;
}

ups_trip_cfg_t ups_trip_config(void)
{
    ups_trip_cfg_t cfg;
    cfg.hi = (uint16_t)UPS_IOUT_PKLIM_DAC_HI;
    cfg.lo = (uint16_t)UPS_IOUT_PKLIM_DAC_LO;
    return cfg;
}

int ups_fout_mode(void)
{
    return UPS_FOUT_MODE;
}

int ups_overload_action(void)
{
    return UPS_OVERLOAD_ACTION;
}
