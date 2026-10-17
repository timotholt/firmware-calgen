/* ups_ctrl.h -- tiny fake UPS controller API used to exercise generated constants.
 *
 * SYNTHETIC DEMO: written for the calgen demo; not from any real product or
 * vendor SDK. There is no control loop here, only the places where generated
 * constants are consumed.
 */
#ifndef UPS_CTRL_H
#define UPS_CTRL_H

#include <stdint.h>

#ifndef CALGEN_HEADER
#error "define CALGEN_HEADER, e.g. -DCALGEN_HEADER='\"calgen_fa10507.h\"'"
#endif
#include CALGEN_HEADER /* defines calgen_num_t: float, or IQ integers on fixed-point targets */

typedef enum { UPS_OL_NORMAL = 0, UPS_OL_ALARM = 1, UPS_OL_TRIP = 2 } ups_ol_state_t;

typedef struct {
    uint16_t period;    /* PWM period register */
    uint16_t deadband;  /* dead-time register */
} ups_pwm_cfg_t;

typedef struct {
    uint16_t hi;  /* comparator DAC code, positive hardware peak-current limit */
    uint16_t lo;  /* comparator DAC code, negative hardware peak-current limit */
} ups_trip_cfg_t;

calgen_num_t ups_vbus_volts(uint16_t adc_counts);
ups_ol_state_t ups_overload_state(calgen_num_t iout_rms);
ups_ol_state_t ups_overload_update(calgen_num_t iout_rms, uint32_t dt_ms, uint32_t *over_ms);
int ups_vout_in_band(calgen_num_t vout_rms);
int ups_battery_low(calgen_num_t vbat);
ups_pwm_cfg_t ups_pwm_config(void);
ups_trip_cfg_t ups_trip_config(void);
int ups_fout_mode(void);
int ups_overload_action(void);

#endif /* UPS_CTRL_H */
