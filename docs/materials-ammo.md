# Materials and ammunition

## Materials

Defined in `armorlab/data.py`: RHA, mild steel, high-hardness steel (500 BHN), Al 5083, Al 7039, Ti-6Al-4V, depleted uranium, Al2O3, SiC, B4C,
UHMWPE, aramid/epoxy, elastomers (rubber, silicone, fluoro-rubber), concrete and thermal insulation. ERA is a separate layer type.

Each entry has density, dynamic yield strength, Tate resistance `Rt`, jet resistance `Rj`, a spall tendency and a source tag `src`:
`measured`, `derived`, `fitted` or `assumed`. Most entries are `assumed` or `fitted`.

### Add your own material

In the program: **Mats** tab (density, yield strength, Rt, Rj, spall tendency; saved to `materials_user.json`).
In code: add `Material(...)` to `MATERIALS` in `armorlab/data.py`.

## Ammunition

Several APFSDS rounds (M829A1, M829A3, DM53, DM63, 3BM42, 3BM60, M735), armor-piercing bullets (14.5 B-32, 12.7 M2 AP, 12.7 B-32, 30 mm),
30 mm tungsten APFSDS, HE fragments (10 / 20 / 50 g), micrometeoroids (5 g and 2 g) and shaped-charge warheads (PG-7V, PG-7VL, TOW-2A, Hellfire, tandem Kornet examples).
Cores: tungsten alloy, depleted uranium, hardened steel, tungsten carbide, aluminium.

### Add your own ammunition

Add `Ammo(...)` to `AMMO` (and the key to `AMMO_ORDER`) in `armorlab/data.py`.
For a new shaped charge set `rated_mm`; the jet length is calibrated to it at start-up.
Run `python selftest.py` afterwards.

## Scenes

Scenes are JSON files in `scenes/` (Scenes tab). Custom materials used by a scene are stored inside the scene file.
