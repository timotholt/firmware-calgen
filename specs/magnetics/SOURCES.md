# Core data sources

Values in `cores.csv` are transcribed from public vendor data sheets (facts only; the PDFs are not redistributed). Read 2026-10-17.

| Core | Data sheet | Revision | Fields used |
|---|---|---|---|
| 0077894A7, 0077071A7, 0077548A7, 0077083A7, 0077439A7, 0077717A7, 0077110A7, 0077908A7 | Magnetics (Spang) Kool Mµ toroid data sheets, `https://www.mag-inc.com/Media/Magnetics/Datasheets/<part>.pdf` | as listed in `cores.csv` | permeability, A_L (nH/T²) ± tolerance, window area W_A, cross section A_e, path length L_e, volume V_e, DC bias in oersteds at 80% and 50% of initial permeability (minimum values) |
| E32/16/9, E42/21/15 (3C94) | Ferroxcube product specifications, `https://www.ferroxcube.com/upload/media/product/file/Pr_ds/<core>.pdf` | 2016 | A_L (ungapped, nH/turn², ±25%), A_e, L_e, V_e, B_sat minimum at 100 °C (25 kHz, 250 A/m), nominal dimensions B, C, E |

**Derived, not stated:** the E-core window area is computed from nominal dimensions as (B − C)/2 × 2E for a core pair, before subtracting the coil former. Bare-core window; the window-fill limit in `limits.yaml` is set lower for E cores to allow for the former and insulation.

**Dimensions** (`od_mm`, `id_mm`, `ht_mm`): uncoated OD, ID, and height for toroids, from the same data sheets. For E cores the columns hold A (overall width), C (center-leg width), and E (window half-height) from the Ferroxcube dimension tables; they are used only to draw the window.

**DC-bias curve fit** (`dc_bias_fit.csv`): Magnetics *Powder Cores* catalog (2025 edition), p. 63, "Permeability versus DC Bias Curves — Fit Formula", Kool Mµ Toroids table: % initial permeability = 1 / (a + b·H^c), H in oersteds; "fit valid only for range shown on graph". This is the vendor's typical curve; checks and sizing scale it so it never exceeds the per-part data sheet minimums (see docs/MAGNETICS_PLAN.md, Phase 3).
