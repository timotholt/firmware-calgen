/* calgen_types.h -- hand-written, stable identifiers used by generated headers.
 *
 * SYNTHETIC DEMO: written for the calgen demo; not from any real product or
 * vendor SDK.
 *
 * Portability note: on TI C28x, char and int are 16 bits and long is 32 bits.
 * This demo is compiled with a host compiler (gcc/clang) as a stand-in for TI
 * Code Composer Studio, which cannot catch C28x-specific width issues. Code
 * here therefore uses <stdint.h> fixed-width types for anything stored.
 */
#ifndef CALGEN_TYPES_H
#define CALGEN_TYPES_H

#include <stdint.h>

/* Output frequency mode */
#define UPS_FOUT_CHANGER  0  /* regenerate a fixed output frequency */
#define UPS_FOUT_FOLLOWER 1  /* track the input frequency */

/* Overload action */
#define UPS_OL_SHUTDOWN 0
#define UPS_OL_BYPASS   1

/* Fixed-point (IQmath-style) storage for targets without an FPU. Each
 * generated header defines calgen_num_t, CALGEN_NUM() and CALGEN_REAL() for
 * its own format, so nothing here depends on include order. */
typedef int32_t calgen_iq_t;

#endif /* CALGEN_TYPES_H */
