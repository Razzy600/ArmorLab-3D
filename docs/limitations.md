# Limitations

ArmorLab is an engineering model of reduced dimensionality. It is not a hydrocode and not a validated design tool.

- **Calibration** uses open order-of-magnitude figures (for example M829A1 about 600 mm RHA, DM53 about 630 mm, TOW-2A about 900 mm). Real values depend on plate properties, range, ammunition version and test method.
- **Material and ammunition data** are approximate. In `armorlab/data.py` every entry carries a `src` tag; most are `assumed` or `fitted`.
- **ERA, core fragmentation, the ricochet criterion, crater shapes and spall** are engineering assumptions. The default ricochet threshold is not calibrated.
- **ERA and ceramic damage radii** are assumptions; no real tile structure is modelled, so multi-hit survivability depends strongly on them.
- **Hypervelocity:** the calibration covers Al on Al at 7–15 km/s, normal impact, and is a fit to a published ballistic-limit equation, not to raw test data. Other materials are extrapolation.
- **Geometry:** the trajectory is straight (no rod deflection by the plate); the series grid ignores parallax of inclined plates.
- **Coefficients** for thermal effects, synergy, defects and self-sharpening are assumptions, not measurements.

Do not use the results for real armor design, certification or the assessment of real systems.
