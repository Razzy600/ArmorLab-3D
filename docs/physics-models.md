# Physics models

All coefficients are assumptions unless the `src` field in `armorlab/data.py` says `measured`; see [Limitations](limitations.md).

## Long rods and bullets

Tate–Alekseevskii model: the penetration velocity `u` follows from
`½ρp(v−u)² + Yp = ½ρt·u² + Rt`, and the rod erodes while it penetrates.
The solver adds brittle-core fragmentation, a ceramic backing effect, a plug / petalling / spall morphology (ULTRA) and an adjustable ricochet threshold.
For short armor-piercing bullets the target resistance is reduced by a factor 0.45 (a fit to open data, not derived).

## Shaped-charge jets

The jet is a set of discrete elements with a velocity gradient, stretching and a velocity cut-off, with Bernoulli hydrodynamics including strength.
The jet length of each warhead is calibrated to its rated penetration. After a ceramic layer the jet loses coherence
(`coherence = max(0.2, 1 − 0.4·t/d)`); an air gap after the ceramic reduces coherence further.
ERA (reactive armor) plates cut the jet elements; tandem warheads fire a precursor first and weaken the layers along the line.

## Hypervelocity (v > 3 km/s)

Compact projectiles (micrometeoroids): Cour-Palais penetration depth, shock-Hugoniot vaporization, and a debris-cloud cone for Whipple shields.
The cloud parameters are fitted to the NASA (Christiansen) ballistic-limit equation for Al on Al at 7–15 km/s, normal impact:
about 7 % error in critical diameter on the fit and about 10 % off the fit. Other materials are extrapolation.

## Spall and spall liner

Rear spall is limited to a layer thickness of at most 1.5·d, and fragment mass is reduced for non-perforated layers.
Layers behind the plate (aramid, PE, rubber) absorb fragment energy in proportion to their mass; metals absorb it by displacement work.

## Witness plate

An RHA witness plate behind the target gives the residual penetration. The "absorbed, RHA-equivalent" figure compares the stack with free RHA.
