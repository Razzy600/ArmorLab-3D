# Engineering calculators

The **Calcs** tab (`armorlab/calc.py`) contains standalone calculators. "Take from target" fills in the current projectile and the selected layer.

| No. | What it computes |
|---|---|
| 1–4 | Alloy by composition (`Fe:70, Cr:18, …`): density 1/Σ(w/ρ), melting point Σ(w·Tm), modulus E (Voigt, Reuss, mean), yield strength with an ODS factor 1.5; 20 elements in the table |
| 5 | De Marre for bullets and fragments: v = K·Kb·d^0.75·h^0.7/√m, impact angle, resistance factor K 0.85–0.95 |
| 6 | Tate–Alekseevskii: u, erosion rate, depth at constant v and with deceleration (integration), non-penetration threshold; matches the solver |
| 7 | Shaped charge P = L·√(ρjet/ρtarget) |
| 8–10 | Aerothermal heat flux ½ρV³C_H (standard atmosphere), ΔT, melting criterion with melt fraction |
| 11–13 | von Mises stress, safety factor n, weld strength K_weld |
| 14 | Areal mass per m² |
| 15 | Equivalent composite thickness by ultimate strength |
| 16 | Impact energy, momentum, TNT equivalent |
| 17 | Impact pressure: ½ρv², ρcv and the shock Hugoniot Us=c0+s·up (impedance matching) |

Formulas 5, 8–10 and 17 use typical handbook constants (De Marre K 2200, element tables, Hugoniots). For anything important, enter your own values.
