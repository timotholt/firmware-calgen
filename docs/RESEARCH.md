# Public research summary

Everything here comes from public sources, accessed 2026-10-16. It informed the demo's assumptions; none of it is a claim about IntelliPower's internal practices.

## Company and products

- IntelliPower (Orange, California) designs ruggedized uninterruptible power systems, frequency converters, and power conditioners for defense and industrial customers; it is part of AMETEK.
- Official data sheets describe "2,000+ variations" built with a "building block methodology", "without having to extend lead times or change proven designs". Model strings encode the options (power, voltage range, frequency mode, isolation, battery chemistry, enclosure).
- Products are described as digital, double-conversion on-line designs with power-factor correction, galvanic isolation on some models, LiFePO4 battery options, and SNMP management.

## The three data sheets used

| Part | Rating | Notable | Revision |
|---|---|---|---|
| FA10449 | 650 VA / 500 W, 120 V | Frequency follower; alarm 105%, shutdown 115% | Rev. 09172021 |
| FA10434 | 800 VA / 560 W, 120 V | Frequency changer; alarm 105%, bypass 115%; 36 V battery | Rev. 09172021 |
| FA10507 | 1500 VA / 1250 W, 85–265 V in | Isolated; "Shutdown at 20% Overload"; 89.6 V LiFePO4 | Rev. 101119 |

Links are in [specs/datasheets/SOURCES.md](../specs/datasheets/SOURCES.md).

### Internal inconsistencies found while transcribing

Every catalog of this size accumulates these; the point is that an automated check finds them before firmware is built from them.

- **FA10434:** the "Input Max Current (Amps)" row reads "50 or 60 Hz" and the "Input Frequency" row reads "7.4 Amps @90VAC Input, 560W Output". The rows hold each other's values.
- **FA10449:** the unit description says "Frequency Changer"; the output frequency row says "60 Hz, Follower".
- **FA10507:** the page-1 header and the specification table print different model numbers (one includes "Isolated").

## Engineering context from public job postings

AMETEK's postings for the Orange and Irvine sites (2025–2026) mention maintaining legacy products, combining legacy boards with newly designed systems, qualifying new or alternate components, DSP-based digital control, and the use of AI tools. A related intern posting describes building a standardized data sheet framework. Together these suggest constants change along three axes: product variant, board revision (alternate parts), and occasionally processor.

## Processor

The AI Automation Intern posting asks for familiarity with TI IDE tools and TI chipsets. TI's C2000 family is its line for digital power control, which makes it the likely platform, but no public document I found names the part. The demo's target profiles are therefore illustrative.
