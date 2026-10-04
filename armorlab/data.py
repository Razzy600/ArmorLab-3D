"""Catalogue of materials, cores and ammunition.

All numbers are approximate, order-of-magnitude values from open sources
(ballistics handbooks, papers on the Tate-Alekseevskii model).
The `src` field honestly marks the origin of each value:
  measured - close to published measurements
  derived  - derived from other quantities
  fitted   - fitted to a published penetration depth
  assumed  - an assumption of the model author
"""
from dataclasses import dataclass, field
import math

GPA = 1e9


@dataclass(frozen=True)
class Material:
    key: str
    name: str
    rho: float          # kg/m3
    yield_gpa: float    # dynamic yield strength, GPa
    rt_gpa: float       # target resistance in Tate model (rods), GPa
    rj_gpa: float       # effective resistance for a shaped-charge jet, GPa
    kind: str           # metal | ceramic | composite | elastomer | concrete
    color: tuple
    spall: float        # tendency to rear-face spalling 0..1
    src: str
    note: str = ""
    user: bool = False
    # optional reference properties (for the Calcs tab), 0 = not set
    e_gpa: float = 0.0
    tm_c: float = 0.0
    c_jkgk: float = 0.0
    k_weld: float = 0.0
    k_stoy: float = 0.0
    spall_gpa: float = 0.0   # dynamic spall strength, GPa (0 = not set; assumption)


MATERIALS = {m.key: m for m in [
    Material("RHA", 'Rolled homogeneous armor steel (RHA)', 7850, 1.00, 5.00, 16.0, "metal", (0.42, 0.45, 0.48), 0.45, "fitted", 'Reference for RHA equivalence'),
    Material("MILD", 'Mild steel', 7850, 0.35, 2.20, 11.0, "metal", (0.50, 0.50, 0.50), 0.15, "assumed"),
    Material("HHS", 'High-hardness steel (500 BHN)', 7850, 1.50, 6.40, 19.0, "metal", (0.30, 0.33, 0.38), 0.75, "assumed", 'Prone to plugging and to breaking up the projectile'),
    Material("AL5083", 'Aluminium 5083', 2660, 0.25, 1.50, 4.5, "metal", (0.72, 0.74, 0.77), 0.20, "derived"),
    Material("AL7039", 'Aluminium 7039', 2740, 0.40, 2.30, 6.0, "metal", (0.68, 0.71, 0.76), 0.35, "derived"),
    Material("TI64", 'Titanium Ti-6Al-4V', 4430, 1.00, 5.00, 13.0, "metal", (0.55, 0.57, 0.62), 0.40, "derived"),
    Material("DU", 'Depleted uranium (armor)', 19050, 1.20, 8.00, 27.0, "metal", (0.22, 0.23, 0.25), 0.30, "assumed"),
    Material("AL2O3", 'Ceramic Al2O3', 3900, 3.00, 11.0, 12.0, "ceramic", (0.90, 0.88, 0.80), 0.90, "assumed", 'Needs a backing, otherwise performs worse', e_gpa=380.0),
    Material("SIC", 'Ceramic SiC', 3200, 4.00, 15.0, 14.0, "ceramic", (0.25, 0.30, 0.28), 0.90, "assumed", 'Needs a backing, otherwise performs worse', e_gpa=410.0),
    Material("B4C", 'Ceramic B4C', 2500, 4.50, 17.0, 15.0, "ceramic", (0.18, 0.18, 0.20), 0.90, "assumed", 'Needs a backing, otherwise performs worse', e_gpa=460.0),
    Material("UHMWPE", 'Polyethylene UHMWPE', 970, 0.15, 1.40, 1.6, "composite", (0.92, 0.93, 0.95), 0.05, "assumed"),
    Material("ARAMID", 'Aramid/epoxy', 1400, 0.20, 1.00, 2.2, "composite", (0.78, 0.66, 0.30), 0.10, "assumed"),
    Material("RUBBER", 'Elastomer', 1100, 0.02, 0.08, 0.6, "elastomer", (0.12, 0.12, 0.12), 0.00, "assumed"),
    Material("SILICONE", 'Silicone rubber (up to +250 °C)', 1150, 0.03, 0.10, 0.7, "elastomer", (0.55, 0.30, 0.30), 0.00, "assumed",
             'Thermal limit ≈ +250 °C'),
    Material("FKM", 'Fluoro-rubber (up to +300 °C)', 1800, 0.04, 0.12, 0.9, "elastomer", (0.20, 0.25, 0.20), 0.00, "assumed",
             'Thermal limit ≈ +300 °C'),
    Material("CONC", 'Concrete', 2400, 0.04, 0.70, 2.0, "concrete", (0.62, 0.61, 0.58), 0.60, "assumed"),
    Material("INSUL", 'Thermal insulation (approximate)', 250, 0.01, 0.06, 0.4, "composite", (0.88, 0.84, 0.70), 0.0, "assumed",
             'Light thermal protection; strength data are nominal, hardly resists penetration'),
]}



# Reactive armor is a special layer type (ERA). Flyer plate parameters.
ERA_KEY = "ERA"
ERA_COLOR = (0.30, 0.34, 0.22)
ERA_FLYER_V = 350.0   # m/s, assumed
ERA_NAME = 'Explosive reactive armor (ERA)'

MATERIAL_ORDER = list(MATERIALS.keys()) + [ERA_KEY]
KINDS = [("metal", 'Metal'), ("ceramic", 'Ceramic'), ("composite", 'Composite'),
         ("elastomer", 'Elastomer'), ("concrete", 'Concrete / brittle stone')]
WITNESS = "RHA"


@dataclass(frozen=True)
class Core:
    key: str
    name: str
    rho: float
    yield_gpa: float     # dynamic strength of the core Yp
    brittle: bool
    color: tuple
    src: str
    sharp: float = 0.0   # self-sharpening: penetration velocity increment in the erosion regime (empirical parameter)


CORES = {c.key: c for c in [
    Core("W", 'Tungsten alloy', 17600, 1.50, False, (0.55, 0.57, 0.62), "assumed"),
    Core("DU", 'Depleted uranium', 18600, 1.20, False, (0.28, 0.28, 0.30), "assumed"),
    Core("STEEL", 'Hardened steel', 7850, 3.00, True, (0.62, 0.52, 0.30), "assumed"),
    Core("WC", 'Tungsten carbide', 15600, 3.20, True, (0.35, 0.35, 0.42), "assumed"),
    Core("AL", 'Aluminium / stony meteoroid (~2.7 g/cm³)', 2700, 0.30, True, (0.70, 0.70, 0.72), "assumed"),
]}

CU_RHO = 8960.0
CU_Y = 0.2


@dataclass(frozen=True)
class Ammo:
    key: str
    name: str
    nation: str
    cls: str            # apfsds | ap | heat
    d_mm: float         # core diameter (kinetic) or shaped-charge liner calibre
    L_mm: float         # core length (kinetic)
    core: str
    v: float            # muzzle/impact velocity, m/s
    nose: str           # pointed | blunt
    src: str
    # shaped charge:
    vt: float = 0.0     # jet tip velocity, m/s
    vmin: float = 0.0   # jet tail velocity, m/s
    s_opt_cd: float = 6.0  # optimal standoff, charge calibres
    rated_mm: float = 0.0  # rated RHA penetration depth, mm
    half_angle: float = 21.0
    liner_mm: float = 2.5
    default_standoff_cd: float = 4.0
    tandem: str = ""      # precursor key (tandem warhead)


AMMO = {a.key: a for a in [
    Ammo("M829A1", 'M829A1 (120 mm APFSDS)', 'USA', "apfsds", 22, 680, "DU", 1575, "pointed", "assumed"),
    Ammo("M829A3", 'M829A3 (120 mm APFSDS)', 'USA', "apfsds", 22, 800, "DU", 1555, "pointed", "assumed"),
    Ammo("DM53", 'DM53 (120 mm APFSDS)', 'Germany', "apfsds", 22, 650, "W", 1750, "pointed", "assumed"),
    Ammo("DM63", 'DM63 (120 mm APFSDS)', 'Germany', "apfsds", 22, 745, "W", 1750, "pointed", "assumed"),
    Ammo("3BM42", '3BM42 "Mango" (125 mm APFSDS)', 'USSR/Russia', "apfsds", 24, 500, "WC", 1700, "pointed", "assumed"),
    Ammo("3BM60", '3BM60 "Svinets-2" (125 mm APFSDS)', 'USSR/Russia', "apfsds", 24, 630, "DU", 1700, "pointed", "assumed"),
    Ammo("M735", 'M735 (105 mm APFSDS)', 'USA', "apfsds", 26, 500, "W", 1490, "pointed", "assumed"),
    Ammo("B32", '14.5×114 B-32 (armor-piercing bullet)', 'USSR/Russia', "ap", 11.0, 50, "STEEL", 1000, "blunt", "assumed"),
    Ammo("M2AP", '12.7×99 M2 AP (armor-piercing bullet)', 'USA', "ap", 10.8, 40, "STEEL", 880, "blunt", "assumed"),
    Ammo("BOPS30", '30×173 APFSDS (30 mm, tungsten)', "—", "apfsds", 10, 140, "W", 1400, "pointed", "assumed"),
    Ammo("AP30", '30×165 AP (30 mm, armor-piercing)', 'USSR/Russia', "ap", 14, 55, "STEEL", 970, "blunt", "assumed"),
    Ammo("FRAG", 'HE fragment (steel, ~10 g, 11 mm cube)', "—", "ap", 11, 11, "STEEL", 1300, "blunt", "assumed"),
    Ammo("B32_127", '12.7×108 B-32 (armor-piercing bullet, 48 g)', 'USSR/Russia', "ap", 10.5, 50, "STEEL", 820, "blunt", "assumed"),
    Ammo("FRAG20", 'HE fragment 20 g (steel, 13.7 mm cube)', "—", "ap", 13.7, 13.7, "STEEL", 1800, "blunt", "assumed"),
    Ammo("METEO5", 'Micrometeoroid 5 g (15 km/s)', "—", "ap", 13.3, 13.3, "AL", 15000, "blunt", "assumed"),
    Ammo("METEO2", 'Micrometeoroid 2 g (8 km/s)', "—", "ap", 9.8, 9.8, "AL", 8000, "blunt", "assumed"),
    Ammo("PG7VL", 'PG-7VL (93 mm, shaped charge)', 'USSR/Russia', "heat", 93, 0, "CU", 300, "pointed", "assumed",
         vt=8300, vmin=1800, s_opt_cd=5.5, rated_mm=500, half_angle=21, liner_mm=2.0),
    Ammo("FRAG50", 'Large HE fragment (steel, ~50 g, 19 mm cube)', "—", "ap", 19, 19, "STEEL", 1000, "blunt", "assumed"),
    Ammo("PG7", 'PG-7V (85 mm, shaped charge)', 'USSR/Russia', "heat", 85, 0, "CU", 300, "pointed", "assumed",
         vt=8200, vmin=1800, s_opt_cd=5.5, rated_mm=330, half_angle=21, liner_mm=2.0),
    Ammo("TOW2A", 'BGM-71 TOW-2A (shaped charge)', 'USA', "heat", 127, 0, "CU", 300, "pointed", "assumed",
         vt=8800, vmin=2000, s_opt_cd=6.0, rated_mm=900, half_angle=22, liner_mm=2.5),
    Ammo("HELLFIRE", 'AGM-114 Hellfire (shaped charge)', 'USA', "heat", 178, 0, "CU", 300, "pointed", "assumed",
         vt=9000, vmin=2000, s_opt_cd=6.0, rated_mm=1000, half_angle=22, liner_mm=3.0),
    Ammo("KORNETM_P", 'Kornet-M precursor (60 mm)', "—", "heat", 60, 0, "CU", 300, "pointed", "assumed",
         vt=7000, vmin=1700, s_opt_cd=5.0, rated_mm=200, half_angle=21, liner_mm=1.5),
    Ammo("KORNETM", 'Kornet-M (tandem, 152 mm)', 'USSR/Russia', "heat", 152, 0, "CU", 300, "pointed", "assumed",
         vt=8500, vmin=2000, s_opt_cd=6.0, rated_mm=1200, half_angle=22, liner_mm=3.0, tandem="KORNETM_P"),
    Ammo("KORNET_P", '63 mm precursor (standalone)', "—", "heat", 63, 0, "CU", 300, "pointed", "assumed",
         vt=7800, vmin=1800, s_opt_cd=5.0, rated_mm=140, half_angle=21, liner_mm=1.5),
    Ammo("KORNET", 'Kornet-E (tandem shaped charge)', 'USSR/Russia', "heat", 152, 0, "CU", 300, "pointed", "assumed",
         vt=9000, vmin=2000, s_opt_cd=6.0, rated_mm=1150, half_angle=22, liner_mm=3.0, tandem="KORNET_P"),
]}
AMMO_ORDER = list(AMMO.keys())


def rod_mass(a: Ammo) -> float:
    c = CORES[a.core]
    r = a.d_mm / 2000.0
    return c.rho * math.pi * r * r * a.L_mm / 1000.0


# ---------------------------------------------------------------- user materials
import json
import os
import re


def _order_insert(key):
    if key in MATERIAL_ORDER:
        return
    i = MATERIAL_ORDER.index(ERA_KEY) if ERA_KEY in MATERIAL_ORDER else len(MATERIAL_ORDER)
    MATERIAL_ORDER.insert(i, key)


def material_to_dict(m: Material):
    return dict(key=m.key, name=m.name, rho=m.rho, yield_gpa=m.yield_gpa, rt_gpa=m.rt_gpa, rj_gpa=m.rj_gpa,
                kind=m.kind, color=list(m.color), spall=m.spall, note=m.note)


def material_from_dict(d):
    return Material(d["key"], d["name"], float(d["rho"]), float(d["yield_gpa"]), float(d["rt_gpa"]),
                    float(d["rj_gpa"]), d.get("kind", "metal"), tuple(d.get("color", (0.5, 0.5, 0.5))),
                    float(d.get("spall", 0.3)), "user", d.get("note", ""), True)


def register_material(m: Material):
    MATERIALS[m.key] = m
    _order_insert(m.key)


def new_user_key(name):
    base = "U_" + (re.sub(r"[^A-Za-z0-9]+", "", name)[:8].upper() or "MAT")
    key, i = base, 1
    while key in MATERIALS:
        i += 1
        key = "%s%d" % (base, i)
    return key


def delete_user_material(key):
    if key in MATERIALS and MATERIALS[key].user:
        del MATERIALS[key]
        if key in MATERIAL_ORDER:
            MATERIAL_ORDER.remove(key)


def user_materials():
    return [m for m in MATERIALS.values() if m.user]


def save_user_materials(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([material_to_dict(m) for m in user_materials()], f, ensure_ascii=False, indent=2)


def load_user_materials(path):
    if not os.path.exists(path):
        return 0
    n = 0
    try:
        with open(path, encoding="utf-8") as f:
            for d in json.load(f):
                register_material(material_from_dict(d))
                n += 1
    except Exception:
        pass
    return n
