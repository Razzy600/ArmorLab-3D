# Getting started

## Install and run

Windows: install Python 3.10–3.13 (3.12 recommended) and double-click `run.bat`.
On the first start it creates a `.venv` and installs Panda3D and NumPy; afterwards it simply opens the program.

Manual start on any platform:

```bash
pip install -r requirements.txt
python main.py
```

Headless regression check of the solver (no window): `python selftest.py`.
Optional standalone `.exe` on Windows: `build_exe.bat` (result in `dist\ArmorLab\`).

## Controls

| Action | Input |
|---|---|
| Rotate camera | LMB on the scene (or arrow keys) |
| Pan | RMB or MMB |
| Zoom | mouse wheel |
| Fire | Space or the FIRE button |
| Pause / reset | P / R |
| Cut-away on/off | C |
| Layer labels | L |
| Hide panels | Tab |
| Solver | 1 / 2 / 3 |
| Quit | Esc |

Ctrl+S saves the scene, Delete removes a layer, the wheel over the list scrolls the layers.

## First shot

1. Open the **Scenes** tab and load `Example1_M829A1_vs_RHA500` (or build your own on the **Target** tab).
2. Pick the ULTRA solver and press **FIRE**.
3. Read the report on the right: per-layer path, velocities, energy, spall and the witness plate result.
