# Conditions, defects and series

All coefficients on this page are assumptions, not measurements.

## Conditions tab ("Cond.")

- **Temperature:** metals lose strength when heated (linearly up to the melting point) and gain a little in the cold; below −30 °C titanium and HHS spall more; ceramic weakens above 1000 °C.
- **Porosity 0–5 %:** density ×(1−P), strength ×(1−2P) for metals and ceramics.
- **Load cycles N:** strength ×N^−0.1; above 0.4·Tm a creep factor ×0.9 is added.
- **Multi-hit:** each layer carries damage D (0 intact, 1 destroyed). "Second shot at the same point" carries D into the layers and fires again with strength ×(1−D).
- **Acoustic interfaces:** Z=ρ·c, Tp=4Z1Z2/(Z1+Z2)². Interfaces with Tp<0.3 are flagged as "decoupled"; this is a report item, not an input to penetration.
- **Elastomer thermal limit:** RUBBER +150 °C, SILICONE +250 °C, FKM +300 °C (assumptions).

## Thermal shock and synergy

`D = 1 − (1−Dth)(1−Dimp) + k·Dth·Dimp`, capped at 1: thermal-shock cracks act as stress concentrators for impact damage.
Dth is stored separately (the layer field `dth`) and carried into the second shot.

## Defects tab

- `K_weld` (weld/HAZ factor): strength of metal layers ×k, spall ×(1+4(1−k)).
- Surface cracks `surf`, %: modelled through the layer damage D.
- Porosity as channels `β` (shaped charges only): effective thickness reduction, heat/jet margin only.
- Self-sharpening `sharp`: increases penetration velocity in the erosion regime (u×(1+sharp)). It is not derived from the Tate equation.
- Hypervelocity mode toggle, external heating (`t_env`, `heat_s`) with 1D transient conduction through the layers, and the ricochet threshold base (default 62°).

## Series tab

Hit dispersion (Gaussian sigma), a 61×61 damage grid per layer (±300 mm), crack transfer between neighbouring layers, local ERA tiles (flat disc of radius 0.15 m),
a damage map with hit markers, and statistics over several series (distribution of the first-penetration hit number).
Parallax of inclined plates is not accounted for in the grid.

## Analysis tab ("Stats")

Monte-Carlo V50 and V05 (material density and strength scatter), four charts (velocity vs depth, energy per layer, mass efficiency vs mass, penetration probability) and CSV/text export.
