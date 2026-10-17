# Data sheet sources

Transcribed by hand from the official, publicly posted IntelliPower data sheets. PDFs are not redistributed here; follow the links.

| Ref | Part | Revision | URL (accessed 2026-10-16) |
|---|---|---|---|
| DS-10449 | FA10449 | Rev. 09172021 | https://www.intellipower.com/-/media/project/ameteksxa/intellipower/2022-ups-pdf-datasheets/fa10449_3-4-22.pdf |
| DS-10434 | FA10434 | Rev. 09172021 | https://www.intellipower.com/-/media/project/ameteksxa/intellipower/2022-ups-pdf-datasheets/fa10434_8-5-21.pdf |
| DS-10507 | FA10507 | Rev. 101119 | https://www.intellipower.com/-/media/project/ameteksxa/intellipower/fa10507-data-sheet.pdf |

## Transcription rules

- `label` and `raw` are copied verbatim from the sheet (row label and cell text), including anything that looks wrong.
- `value` / `unit` are the normalized reading. Where a value needed arithmetic or interpretation (e.g. `120 VAC (-25% +15%)` → 90 V / 138 V; `Shutdown at 20% Overload` → 120 %), the `source` column says so.
- When a printed cell cannot be read as the quantity its label promises (FA10434's input current and input frequency rows hold each other's values), `value` is left empty. The data sheet consistency gate flags it, and the variant file must carry an explicit, reasoned override.

Ratings are public product data. All circuit values, gains, and firmware names in this repository are invented.
