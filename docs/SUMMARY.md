# One-page summary

**What it is.** A tool that turns a product's data sheet plus a board and processor description into the firmware constants that protect and regulate the product, and refuses to produce anything when the inputs don't add up.

**The problem it addresses.** Firmware for a configure-to-order catalog carries dozens of hand-typed numbers per variant: limits, trip levels, sensor scale factors, timer settings. They are recomputed by hand when a variant is added or a component is substituted. Mistakes are hard to see in review and can be safety-relevant.

**What it does differently.**
- Every number shows where it came from, down to the quoted data sheet line, and the math can be checked on paper.
- It checks the data sheet against itself first. All three public data sheets used here had an inconsistency.
- It catches the dangerous cases automatically: a substituted sensor amplifier that would let current exceed the sensor's range before the hardware peak limit fires; tuning values whose design basis has changed.
- It can audit existing firmware read-only, which is how adoption would start: the demo's legacy code had 3 of 33 values that contradict the data sheet, 9 that differ from design values, and a fast-trip level that would shut down a fully loaded unit.

**Where AI fits.** A low-cost model drafts what unexplained legacy constants mean; a person approves. Scored against a blind answer key over three runs on a 33-constant synthetic set, gpt-5.4-nano maps constants to the right rule 96% of the time, but its category labels (85%) miss the bar I set in advance, so I report it as below the bar. About half a cent per run. The firmware itself is never written by AI. On controlled data, the AI step uses an approved internal model or is turned off.

**What it is not.** It doesn't design power stages, tune control loops, or replace certification. It removes transcription and bookkeeping errors and leaves a review record.

**Suggested first month.** Week 1: audit one product's firmware against its data sheet (read-only). Weeks 2–3: agree the spec format and rules for that product with its engineers. Week 4: generate its constants behind the same review and build checks the team uses today, and measure time saved on the next variant.
