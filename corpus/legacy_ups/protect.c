/* SYNTHETIC EXAMPLE — written for the calgen demo. Not from any real product
 * or vendor SDK. Names and values are invented to resemble typical
 * power-converter firmware. May not compile on any target. */

/* protect.c -- fast (per-cycle) and slow (1 ms) protection */
#include "ups_config.h"
#include "sense_scale.h"

#define FLT_LOG_LEN     16

enum { FLT_OC = 1, FLT_OL, FLT_UVB, FLT_OVO, FLT_BRN };

static const float k_trip_a = 15.0f;            /* A rms, overload trip */
static const unsigned short ol_hold_ms = 5000;  /* overload ride-through */

static unsigned char flt_log[FLT_LOG_LEN];
static unsigned char flt_idx;
static unsigned short ol_ms;
static unsigned char retry;

extern void inv_off(void);
extern void inv_on(void);
extern void delay_ms(unsigned short ms);

static void log_fault(unsigned char code)
{
    flt_log[flt_idx++ & (FLT_LOG_LEN - 1)] = code;
}

void prot_fast(float i_pk)
{
    float a = (i_pk < 0.0f) ? -i_pk : i_pk;

    if (a > 21.2f) {                       /* peak of the RMS trip level */
        inv_off();
        log_fault(FLT_OC);
    }
}

void prot_slow(float i_rms, float vbat, float vo_rms)
{
    if (i_rms > k_trip_a) {
        if (++ol_ms >= ol_hold_ms) { inv_off(); log_fault(FLT_OL); }
    } else if (ol_ms) {
        ol_ms--;
    }
    if (vbat < VBAT_CUT)          { inv_off(); log_fault(FLT_UVB); }
    if (vo_rms > VO_HI)           { inv_off(); log_fault(FLT_OVO); }
    if (vo_rms < 0.9f * VO_NOM)   { log_fault(FLT_BRN); }
}

void prot_restart(void)
{
    if (retry < 3) {
        delay_ms(500);
        retry++;
        inv_on();
    }
}
