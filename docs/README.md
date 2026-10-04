# ArmorLab 3D

ArmorLab 3D is a desktop 3D armor-penetration simulator written in Python (Panda3D and NumPy).
You build a target from plates (material, thickness, obliquity, air gap), choose a projectile and fire.
The scene shows rod or jet erosion, crater, plug, petalling, spall and a cut-away of the channel.

{% hint style="warning" %}
**Research and educational prototype.** The model is reduced-order, not a hydrocode, and it is not validated for design work.
Most material and ammunition values are order-of-magnitude assumptions (see [Limitations](limitations.md)).
Do not use the output for real armor design, certification or safety-critical decisions.
{% endhint %}

## What you get

- Three solver levels: NORMAL, ADVANCED and ULTRA (adds crater morphology).
- Long rods and bullets (Tate–Alekseevskii), shaped-charge jets, tandem warheads, ERA, hypervelocity impacts.
- Conditions: temperature, porosity, load cycles, accumulated damage, thermal shock, welded seams, surface cracks, 1D heating.
- Hit series with dispersion and a 2D damage grid, Monte-Carlo V50, 17 engineering calculators.

Start with [Getting started](getting-started.md).
