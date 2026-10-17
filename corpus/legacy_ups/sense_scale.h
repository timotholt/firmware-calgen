/* SYNTHETIC EXAMPLE — written for the calgen demo. Not from any real product
 * or vendor SDK. Names and values are invented to resemble typical
 * power-converter firmware. May not compile on any target. */

/* sense_scale.h -- ADC / comparator scaling for the sense chain */
#ifndef SENSE_SCALE_H
#define SENSE_SCALE_H

#define ADC_FULL        4095.0f     /* 12-bit converter                   */
#define DAC_FULL        4095        /* comparator reference DAC           */

/* DC bus: 1.5 M / 10 k divider */
#define VBUS_FS         498.3f      /* V at ADC full scale                */
#define K_VS            (VBUS_FS / ADC_FULL)    /* V per count            */

/* battery: 499 k / 10 k divider */
#define VBAT_FS         168.0f      /* V at ADC full scale                */

/* output voltage, mid-rail biased */
#define VO_FS_PK        501.6f      /* peak V at +/- half scale           */

/* output current: 5 mOhm shunt into x10 amp, mid-rail biased */
#define IO_FS_PK        33.0f       /* peak A at +/- half scale           */
#define CMP_DAC_HI      3364        /* positive overcurrent trip code     */
#define CMP_DAC_LO      (DAC_FULL - CMP_DAC_HI)

#endif /* SENSE_SCALE_H */
