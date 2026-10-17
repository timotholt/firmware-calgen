/* SYNTHETIC EXAMPLE — written for the calgen demo. Not from any real product
 * or vendor SDK. Names and values are invented to resemble typical
 * power-converter firmware. May not compile on any target. */

/*
 * ups_config.h -- 1500 VA on-line UPS, main controller settings
 *
 * History (hand-maintained):
 *   2009-03  first cut, carried over from the 1250 VA export board  (JR)
 *   2011-08  domestic 120 V / 60 Hz build                          (MK)
 *   2014-02  lithium battery option                                (MK)
 *
 * NOTE: keep in sync with sense_scale.h if the divider changes.
 */
#ifndef UPS_CONFIG_H
#define UPS_CONFIG_H

/* ---- firmware id ------------------------------------------------------ */
#define FW_VER_MAJ      2

/* ---- AC input window -------------------------------------------------- */
#define VIN_LO_XFER     85.0f       /* go to battery below this, Vrms     */
#define VIN_HI_XFER     265.0f      /* go to battery above this, Vrms     */

/* ---- DC bus ----------------------------------------------------------- */
#define VBUS_REF        400.0f      /* PFC regulation target, V           */

/* ---- inverter / output ------------------------------------------------ */
#define VO_NOM          220.0f      /* output, Vrms                       */
#define VO_TOL          0.03f       /* +/- regulation band                */
#define VO_HI           (VO_NOM * (1.0f + VO_TOL))
#define IO_RATED        12.5f       /* A rms, 1500 VA / 120 V             */
#define I_TRIP_RMS      14.0f       /* overload shutdown, A rms           */

/* ---- PWM -------------------------------------------------------------- */
#define TMR_LD          6000        /* PWM period, 25 kHz carrier         */
#define DB_CNT          30          /* 300 us dead time                   */

/* ---- voltage loop (do not touch without power eng sign-off) ----------- */
#define K_P             0.8f
#define K_I             0.015f      /* per control ISR                    */

/* ---- battery ---------------------------------------------------------- */
#define VBAT_NOM        89.6f       /* string nominal, V                  */
#define VBAT_CUT        78.4f       /* end of discharge, 1.75 V/cell      */

/* ---- comms / IO ------------------------------------------------------- */
#define UART_BAUD       19200       /* front-panel / RS-232 port          */
#define PIN_BYP_RELAY   12          /* GPIO, static bypass relay drive    */

#endif /* UPS_CONFIG_H */
