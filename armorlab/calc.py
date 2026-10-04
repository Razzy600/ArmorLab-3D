"""Engineering formulas (no graphics): alloys, penetration, thermal protection, strength.

Each calculator: Calc(key, group, title, fields, fn, note).
fields: list of Field(key, label, default, text=False). fn(values) -> list of strings.
Input units are engineering (mm, g, MPa, GPa, m/s, kg/m3); internally everything is computed in SI.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Callable, List


# ---------------------------------------------------------------------------
# Reference data (rounded tabulated values for pure elements)
# rho kg/m3, Tm °C, E GPa, c J/(kg*K), Hf kJ/kg
# ---------------------------------------------------------------------------
ELEMENTS = {
    "Fe": dict(rho=7874, Tm=1538, E=211, c=449, Hf=247),
    "C":  dict(rho=2267, Tm=3550, E=10,  c=710, Hf=0),     # graphite; melts only under pressure
    "Cr": dict(rho=7190, Tm=1907, E=279, c=449, Hf=404),
    "Ni": dict(rho=8908, Tm=1455, E=200, c=444, Hf=298),
    "Mo": dict(rho=10280, Tm=2623, E=329, c=251, Hf=375),
    "Mn": dict(rho=7470, Tm=1246, E=198, c=479, Hf=268),
    "Si": dict(rho=2330, Tm=1414, E=130, c=705, Hf=1790),
    "V":  dict(rho=6110, Tm=1910, E=128, c=489, Hf=422),
    "W":  dict(rho=19250, Tm=3422, E=411, c=132, Hf=192),
    "Al": dict(rho=2700, Tm=660, E=70,  c=897, Hf=397),
    "Ti": dict(rho=4506, Tm=1668, E=116, c=523, Hf=295),
    "Cu": dict(rho=8960, Tm=1085, E=130, c=385, Hf=209),
    "Mg": dict(rho=1738, Tm=650, E=45,  c=1023, Hf=368),
    "Zn": dict(rho=7140, Tm=420, E=108, c=388, Hf=112),
    "Y":  dict(rho=4472, Tm=1526, E=64,  c=298, Hf=128),
    "Co": dict(rho=8900, Tm=1495, E=209, c=421, Hf=260),
    "Nb": dict(rho=8570, Tm=2477, E=105, c=265, Hf=290),
    "Ta": dict(rho=16650, Tm=3017, E=186, c=140, Hf=174),
    "U":  dict(rho=19050, Tm=1132, E=208, c=116, Hf=38),
    "Zr": dict(rho=6511, Tm=1855, E=88,  c=278, Hf=250),
}

# shock Hugoniots Us = c0 + s*up (typical reference values)
HUGONIOT = {
    "Fe": dict(rho=7850, c0=4570, s=1.49, name='steel'),
    "Al": dict(rho=2700, c0=5350, s=1.34, name='aluminium'),
    "Cu": dict(rho=8930, c0=3940, s=1.489, name='copper'),
    "W":  dict(rho=17600, c0=4030, s=1.237, name='tungsten'),
    "Ti": dict(rho=4430, c0=5130, s=1.028, name='titanium Ti-6Al-4V'),
    "U":  dict(rho=18950, c0=2487, s=2.20, name='uranium'),
    "Ta": dict(rho=16650, c0=3414, s=1.20, name='tantalum'),
}

K_DEMARRE = 2200.0   # base De Marre constant (kg, dm, m/s) for medium-hardness steel armor


def parse_comp(text):
    """'Fe:70, Cr:18, Ni:8, Mo:4' -> {'Fe':0.70,...} (normalised to 1). Returns (comp, warning)."""
    comp = {}
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            k, v = part.split(":", 1)
        elif "=" in part:
            k, v = part.split("=", 1)
        else:
            raise ValueError('cannot parse "%s": expected Symbol:fraction' % part)
        k = k.strip().capitalize()
        v = float(v.strip().replace(",", ".").replace("%", ""))
        if k not in ELEMENTS:
            raise ValueError('no element "%s". Available: %s' % (k, " ".join(ELEMENTS)))
        comp[k] = comp.get(k, 0.0) + v
    if not comp:
        raise ValueError('empty composition')
    s = sum(comp.values())
    if s <= 0:
        raise ValueError('sum of fractions must be > 0')
    warn = ""
    if abs(s - 1.0) > 1e-6 and abs(s - 100.0) > 1e-6:
        warn = 'sum of fractions %.4g - normalised to 1' % s
    elif abs(s - 100.0) < 1e-6:
        warn = ""
    return {k: v / s for k, v in comp.items()}, warn


# ---------------------------------------------------------------------------
# 1–4 Alloy
# ---------------------------------------------------------------------------
def alloy_density(w):
    """1/rho = sum(w_i/rho_i) (volume additivity). w - mass fractions."""
    return 1.0 / sum(wi / ELEMENTS[k]["rho"] for k, wi in w.items())


def alloy_Tm(w):
    """Tm = sum(w_i * Tm_i), °C (linear rule of mixtures; the real solidus is lower)."""
    return sum(wi * ELEMENTS[k]["Tm"] for k, wi in w.items())


def alloy_E(w):
    """Elastic modulus. Returns (Voigt, Reuss, Hill) in GPa; averaged by volume fractions."""
    rho = alloy_density(w)
    vf = {k: wi * rho / ELEMENTS[k]["rho"] for k, wi in w.items()}
    voigt = sum(vf[k] * ELEMENTS[k]["E"] for k in w)
    reuss = 1.0 / sum(vf[k] / ELEMENTS[k]["E"] for k in w)
    return voigt, reuss, 0.5 * (voigt + reuss)


def yield_ods(sy, factor=1.5):
    """sigma_y,ODS = sigma_y * ODS_factor."""
    return sy * factor


# ---------------------------------------------------------------------------
# 5 De Marre
# ---------------------------------------------------------------------------
def demarre_h(v, m, d, alpha_deg=0.0, K=0.9, Kbase=K_DEMARRE):
    """Penetration path along the line of sight (effective thickness), m. v in m/s, m in kg, d in m.
    K - armor resistance factor (0.85-0.95). alpha_deg is kept for consistency: normal thickness = h*cos(alpha)."""
    h_dm = (v * math.sqrt(m) / (K * Kbase * (d * 10.0) ** 0.75)) ** (1.0 / 0.7)
    return h_dm / 10.0


def demarre_v(h, m, d, alpha_deg=0.0, K=0.9, Kbase=K_DEMARRE):
    """Ballistic limit velocity for a plate of thickness h (m) measured along the normal, with obliquity correction: h_eff = h/cos(alpha)."""
    ca = math.cos(math.radians(min(alpha_deg, 85.0)))
    h_eff_dm = (h / ca) * 10.0
    return K * Kbase * (d * 10.0) ** 0.75 * h_eff_dm ** 0.7 / math.sqrt(m)


# ---------------------------------------------------------------------------
# 6 Tate–Alekseevskii
# ---------------------------------------------------------------------------
def tate_u(v, rho_p, rho_t, Yp, Rt):
    """Penetration velocity u from ½ρp(v-u)² + Yp = ½ρt·u² + Rt.
    Returns (u, regime, discriminant). Regimes: 'erosion', 'rigid' (rod does not erode), 'none' (no penetration)."""
    if v <= 0:
        return 0.0, 'none', 0.0
    if Rt <= Yp and v * v <= 2.0 * (Yp - Rt) / rho_t:
        return v, 'rigid', 0.0
    if Rt > Yp and v * v <= 2.0 * (Rt - Yp) / rho_p:
        return 0.0, 'none', 0.0
    A, B, D = rho_p, rho_t, 2.0 * (Rt - Yp)
    disc = A * B * v * v + (A - B) * D
    if abs(A - B) < 1e-9:
        u = (A * v * v - D) / (2 * A * v)
    elif disc < 0:
        return 0.0, 'none', disc
    else:
        s = math.sqrt(disc)
        cands = [(A * v - s) / (A - B), (A * v + s) / (A - B)]
        cands = [x for x in cands if -1e-9 <= x <= v + 1e-9]
        if not cands:
            return 0.0, 'none', disc
        u = min(cands)
    if u <= 0:
        return 0.0, 'none', disc
    return min(u, v), 'erosion', disc


def tate_depth(L, v, rho_p, rho_t, Yp, Rt):
    """Tate integration: dP/dt = u, dL/dt = -(v-u), ρp·L·dv/dt = -Yp (erosion regime).
    Returns (P at v=const, integrated P, final velocity)."""
    u, reg, _ = tate_u(v, rho_p, rho_t, Yp, Rt)
    if reg == 'none':
        return 0.0, 0.0, 0.0
    p_stat = L * u / (v - u) if v - u > 1e-6 else float("inf")
    Lc, vc, P, t = L, v, 0.0, 0.0
    t_ref = L / max(v - u, 1.0)
    for _ in range(400000):
        uu, rg, _ = tate_u(vc, rho_p, rho_t, Yp, Rt)
        if rg == 'none' or Lc <= 1e-4 * L:
            break
        e = vc - uu
        if rg == 'rigid':
            decel = (0.5 * rho_t * vc * vc + Rt) / (rho_p * Lc)
        else:
            decel = Yp / (rho_p * Lc)
        dt = t_ref / 3000.0
        if e > 0:
            dt = min(dt, 0.01 * Lc / e)
        dt = min(dt, 0.01 * vc / max(decel, 1e-9))
        P += uu * dt
        Lc -= e * dt
        vc -= decel * dt
        t += dt
        if vc <= 0:
            break
    return p_stat, P, max(vc, 0.0)


# ---------------------------------------------------------------------------
# 7 Shaped charge
# ---------------------------------------------------------------------------
def jet_depth(L_jet, rho_jet, rho_t):
    """P = L * sqrt(rho_jet / rho_target)."""
    return L_jet * math.sqrt(rho_jet / rho_t)


# ---------------------------------------------------------------------------
# 8–10 Thermal protection
# ---------------------------------------------------------------------------
def air_density(alt_m):
    """Standard atmosphere (ISA): troposphere up to 11 km, above it an isothermal layer up to 25 km and a barometric model."""
    if alt_m < 0:
        alt_m = 0.0
    if alt_m <= 11000:
        T = 288.15 - 0.0065 * alt_m
        p = 101325.0 * (T / 288.15) ** 5.2559
    elif alt_m <= 25000:
        T = 216.65
        p = 22632.1 * math.exp(-9.80665 * (alt_m - 11000) / (287.053 * T))
    else:
        T = 216.65 + 0.003 * (alt_m - 25000)
        p = 2488.7 * (T / 221.65) ** -11.388 if T > 0 else 0.0
        if alt_m > 47000:
            T = 270.65
            p = 110.9 * math.exp(-9.80665 * (alt_m - 47000) / (287.053 * T))
    return p / (287.053 * T)


def heat_flux(rho_air, V, CH):
    """q = ½ ρ V³ C_H, W/m²."""
    return 0.5 * rho_air * V ** 3 * CH


# ---------------------------------------------------------------------------
# 11–13 Strength
# ---------------------------------------------------------------------------
def von_mises(s1, s2, s3):
    return math.sqrt(0.5 * ((s1 - s2) ** 2 + (s2 - s3) ** 2 + (s3 - s1) ** 2))


# ---------------------------------------------------------------------------
# 17 Impact pressure
# ---------------------------------------------------------------------------
def impact_pressure(mat_p, mat_t, v):
    """Planar impact by the impedance-matching method (Us = c0 + s up). Returns (P, up_target, up_proj)."""
    p, t = HUGONIOT[mat_p], HUGONIOT[mat_t]

    def f(u):  # u - particle velocity in the target
        up = v - u
        Pt = t["rho"] * (t["c0"] + t["s"] * u) * u
        Pp = p["rho"] * (p["c0"] + p["s"] * up) * up
        return Pp - Pt
    lo, hi = 0.0, v
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    u = 0.5 * (lo + hi)
    return t["rho"] * (t["c0"] + t["s"] * u) * u, u, v - u


# ---------------------------------------------------------------------------
# Calculator descriptions for the UI
# ---------------------------------------------------------------------------
@dataclass
class Field:
    key: str
    label: str
    default: str
    text: bool = False


@dataclass
class Calc:
    key: str
    group: str
    title: str
    fields: List[Field]
    fn: Callable
    note: str = ""


def _f(v, k):
    return float(str(v[k]).replace(",", "."))


def c_alloy(v):
    w, warn = parse_comp(str(v["comp"]))
    rho = alloy_density(w)
    Tm = alloy_Tm(w)
    Ev, Er, Eh = alloy_E(w)
    sy = _f(v, "sy")
    kf = _f(v, "ods")
    L = []
    if warn:
        L.append("! " + warn)
    L.append('composition (mass fractions): ' + ", ".join("%s %.3f" % (k, x) for k, x in sorted(w.items(), key=lambda a: -a[1])))
    L.append('[1] density  ρ = 1/Σ(w/ρi) ..... %.0f kg/m³' % rho)
    L.append('[2] T melt Σ(w·Tm_i) .......... %.0f °C' % Tm)
    L.append('[3] modulus E: Voigt %.0f / Reuss %.0f / mean %.0f GPa' % (Ev, Er, Eh))
    L.append('[4] σy ODS = σy·%.2f ............. %.0f MPa  (was %.0f)' % (kf, yield_ods(sy, kf), sy))
    L.append("")
    L.append('Linear melting T is an upper estimate; the real')
    L.append('solidus is lower. E by volume fractions; the true E depends')
    L.append('on phases and texture.')
    return L


def c_demarre(v):
    d = _f(v, "d") / 1000.0
    m = _f(v, "m") / 1000.0
    vel = _f(v, "v")
    al = _f(v, "al")
    K = _f(v, "K")
    h = _f(v, "h") / 1000.0
    L = []
    hh = demarre_h(vel, m, d, 0.0, K)
    ca = math.cos(math.radians(min(al, 85.0)))
    L.append('[5] De Marre: v = K·Kb·d^0.75·h^0.7/√m, (dm, kg)')
    L.append('penetration path at v=%.0f m/s: %.1f mm' % (vel, hh * 1000))
    if al > 0:
        L.append('plate at %.0f°: normal thickness %.1f mm' % (al, hh * ca * 1000))
    vl = demarre_v(h, m, d, al, K)
    L.append('limit velocity for a %.0f mm plate at %.0f°: %.0f m/s' % (h * 1000, al, vl))
    L.append("")
    L.append('Kb = %.0f (medium-hardness steel), K = resistance factor.' % K_DEMARRE)
    L.append('Not applicable to APFSDS and shaped charges: see [6], [7].')
    return L


def c_tate(v):
    Lr = _f(v, "L") / 1000.0
    vel = _f(v, "v")
    rp = _f(v, "rp")
    rt = _f(v, "rt")
    Yp = _f(v, "Yp") * 1e9
    Rt = _f(v, "Rt") * 1e9
    u, reg, disc = tate_u(vel, rp, rt, Yp, Rt)
    L = ['[6] Tate–Alekseevskii: ½ρp(v-u)² + Yp = ½ρt·u² + Rt']
    L.append('radicand: %.4g %s' % (disc, '(< 0: no penetration)' if disc < 0 else ""))
    if reg == 'none':
        L.append('u = 0 → armor is not penetrated at v = %.0f m/s' % vel)
        vc = math.sqrt(max(2 * (Rt - Yp) / rp, 0.0))
        L.append('threshold v_c = √(2(Rt-Yp)/ρp) = %.0f m/s' % vc)
        return L
    ps, pi, vend = tate_depth(Lr, vel, rp, rt, Yp, Rt)
    if reg == 'rigid':
        L.append('regime: rigid rod (does not erode)')
    L.append('penetration velocity u = %.0f m/s' % u)
    L.append('erosion velocity  v-u = %.0f m/s' % (vel - u))
    L.append('depth, v=const: P = L·u/(v-u) ... %.0f mm' % (ps * 1000))
    L.append('depth with deceleration (integr.) ... %.0f mm' % (pi * 1000))
    L.append('residual rod velocity ........... %.0f m/s' % max(vend, 0))
    L.append("P/L = %.2f" % (pi / Lr if Lr else 0))
    L.append("")
    L.append('The integrated value is closer to reality: the rod')
    L.append('decelerates. Rt and Yp are effective values, fitted to')
    L.append('test data. Rod and plate density in kg/m³.')
    return L


def c_jet(v):
    Lj = _f(v, "L") / 1000.0
    rj = _f(v, "rj")
    rt = _f(v, "rt")
    P = jet_depth(Lj, rj, rt)
    L = ['[7] hydrodynamics: P = L·√(ρjet/ρtarget)']
    L.append("√(ρj/ρt) = %.3f" % math.sqrt(rj / rt))
    L.append('depth P = %.0f mm' % (P * 1000))
    L.append("")
    L.append('Length is the total length of the continuous (not broken-up)')
    L.append('part of the jet. Real penetration is smaller: target')
    L.append('strength, jet breakup, and drift (see shaped charge in the Target tab).')
    return L


def c_thermal(v):
    alt = _f(v, "alt") * 1000.0
    V = _f(v, "V")
    CH = _f(v, "CH")
    A = _f(v, "A")
    t = _f(v, "t")
    m = _f(v, "m")
    c = _f(v, "c")
    T0 = _f(v, "T0")
    Tm = _f(v, "Tm")
    Hf = _f(v, "Hf") * 1000.0
    el = str(v.get("el", "")).strip().capitalize()
    L = []
    if el:
        if el not in ELEMENTS:
            raise ValueError('no element "%s"' % el)
        e = ELEMENTS[el]
        c, Tm, Hf = e["c"], float(e["Tm"]), e["Hf"] * 1000.0
        L.append('material: %s (c=%d, Tm=%d °C, Hf=%d kJ/kg)' % (el, c, Tm, Hf / 1000))
    rho = air_density(alt)
    q = heat_flux(rho, V, CH)
    Qin = q * A * t
    dT = Qin / (m * c)
    Qheat = m * c * (Tm - T0)
    Qtot = Qheat + m * Hf
    L.append('[8] ρ_air(%.1f km) = %.4f kg/m³' % (alt / 1000, rho))
    L.append('    q = ½ρV³C_H = %.3g W/m²' % q)
    L.append("[9] ΔT = qAt/(mc) = %.0f °C  →  T = %.0f °C" % (dT, T0 + dT))
    L.append('[10] heat input Q = %.4g J' % Qin)
    L.append('     heating to Tm %.4g J + melting %.4g J' % (Qheat, m * Hf))
    L.append('     total to full melting %.4g J' % Qtot)
    if Qin > Qtot:
        L.append('     Q_in > Q_total → PART MELTS completely')
    elif Qin > Qheat:
        fr = (Qin - Qheat) / (m * Hf) if Hf > 0 else 1.0
        L.append('     melting T reached, %.0f%% of mass melted' % (100 * fr))
    else:
        L.append('     does not melt, heat margin %.0f%%' % (100 * (1 - Qin / Qheat) if Qheat > 0 else 0))
        if q > 0:
            L.append('     time to melting ≈ %.1f s' % (Qheat / (q * A)))
    L.append("")
    L.append('Model: uniform heating without radiation or heat conduction')
    L.append('(conservative). C_H = 1e-4…1e-3.')
    return L


def c_strength(v):
    s1, s2, s3 = _f(v, "s1"), _f(v, "s2"), _f(v, "s3")
    sy = _f(v, "sy")
    Kw = _f(v, "Kw")
    nreq = _f(v, "nreq")
    svm = von_mises(s1, s2, s3)
    L = ['[11] σ_vM = √(½[(σ1-σ2)²+(σ2-σ3)²+(σ3-σ1)²]) = %.1f MPa' % svm]
    L.append('     σ_vM %s σy (%.0f) → %s' % ("<" if svm < sy else "≥", sy, 'holds' if svm < sy else 'yields'))
    n = sy / svm if svm > 0 else float("inf")
    L.append('[12] margin n = σy/σ_vM = %s (required ≥ %.2f) → %s' % (("%.2f" % n) if svm > 0 else "∞", nreq, "OK" if n >= nreq else 'INSUFFICIENT'))
    sw = Kw * sy
    L.append('[13] σ_weld = K_weld·σy = %.0f MPa' % sw)
    L.append('     σ_vM %s σ_weld → %s' % (">" if svm > sw else "≤", 'WELD FAILURE' if svm > sw else 'weld holds'))
    if svm > 0:
        L.append('     weld margin %.2f' % (sw / svm))
    L.append("")
    L.append('Aviation n ≥ 1.2–1.5, tanks n ≥ 2.0. TIG K=0.85–0.95,')
    L.append('laser K=0.95–1.0.')
    return L


def c_mass(v):
    rho = _f(v, "rho")
    h = _f(v, "h") / 1000.0
    A = _f(v, "A")
    m = rho * h
    L = ['[14] mass per 1 m²: m = ρ·h = %.1f kg/m²' % m]
    L.append('area %.3g m² → %.1f kg' % (A, m * A))
    L.append('RHA equivalent by mass: %.1f mm' % (m / 7850 * 1000))
    return L


def c_equiv(v):
    sst = _f(v, "sst")
    items = []
    for part in str(v["layers"]).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        a, b = part.split("/")
        items.append((float(a.replace(",", ".")), float(b.replace(",", "."))))
    if not items:
        raise ValueError('no layers: format "10/1500, 20/900" (mm / MPa)')
    heq = sum(h * s / sst for h, s in items)
    L = ['[15] h_eq = Σ h_i·σB_i / σB_steel']
    for i, (h, s) in enumerate(items, 1):
        L.append('  layer %d: %.1f mm · %.0f MPa → %.1f mm' % (i, h, s, h * s / sst))
    L.append('h_eq = %.1f mm of steel (σB=%.0f MPa), total %.1f mm' % (heq, sst, sum(h for h, _ in items)))
    L.append("")
    L.append('Strength equivalence is a rough estimate; for')
    L.append('penetration, compute the layers more accurately in the "Target" tab.')
    return L


def c_energy(v):
    m = _f(v, "m") / 1000.0
    vel = _f(v, "v")
    E = 0.5 * m * vel * vel
    return ['[16] E = ½·m·v² = %.4g J = %.3f kJ' % (E, E / 1000),
            'momentum p = m·v = %.3g N·s' % (m * vel),
            'in TNT equivalent: %.3g g TNT' % (E / 4.184e3)]


def c_impedance(v):
    r1, c1, r2, c2 = _f(v, "r1"), _f(v, "c1"), _f(v, "r2"), _f(v, "c2")
    if min(r1, c1, r2, c2) <= 0:
        raise ValueError('all values must be greater than zero')
    z1, z2 = r1 * c1, r2 * c2
    tp = 4 * z1 * z2 / (z1 + z2) ** 2
    rr = ((z2 - z1) / (z1 + z2)) ** 2
    L = ['[14] acoustic impedance of the layer boundary']
    L.append('Z1 = ρ1·c1 ................. %.3g kg/(m²·s)' % z1)
    L.append('Z2 = ρ2·c2 ................. %.3g kg/(m²·s)' % z2)
    L.append('pressure transmission Tp ... %.3f' % tp)
    L.append('energy reflection .......... %.3f' % rr)
    L.append('wave in layer 2: ' + ('boundary is an acoustic decoupler (Tp<0.3)' if tp < 0.3 else 'transmitted in a significant fraction'))
    L.append('Pressure transmission coefficient 4Z1Z2/(Z1+Z2)²; does not affect penetration in the model.')
    return L


def c_pressure(v):
    mp = str(v["mp"]).strip().capitalize()
    mt = str(v["mt"]).strip().capitalize()
    if mp not in HUGONIOT or mt not in HUGONIOT:
        raise ValueError('materials: ' + " ".join(HUGONIOT))
    vel = _f(v, "v")
    P, ut, up = impact_pressure(mp, mt, vel)
    p, t = HUGONIOT[mp], HUGONIOT[mt]
    L = ['[17] impact pressure, %s → %s, v = %.0f m/s' % (p["name"], t["name"], vel)]
    L.append('stagnation  ½ρv² (projectile) ... %.2f GPa' % (0.5 * p["rho"] * vel ** 2 / 1e9))
    L.append('acoustic   ρ·c·v (target) ..... %.2f GPa' % (t["rho"] * t["c0"] * vel / 1e9))
    L.append('shock Hugoniot Us=c0+s·up:')
    L.append('  P = ρ0·Us·up ................. %.2f GPa' % (P / 1e9))
    L.append('  particle velocity: target %.0f, projectile %.0f m/s' % (ut, up))
    L.append("")
    L.append('Planar impact, one-dimensional theory. For hardness and')
    L.append('penetration strength, Rt/Yp are needed (see [6]).')
    L.append('Materials: ' + " ".join("%s=%s" % (k, h["name"]) for k, h in HUGONIOT.items()))
    return L


CALCS: List[Calc] = [
    Calc("alloy", 'Material', 'Alloy [1–4]: ρ, Tmelt, E, σy ODS', [
        Field("comp", 'Composition: Symbol:fraction (e.g. Fe:70, Cr:18, Ni:8, Mo:4)', "Fe:0.70, Cr:0.18, Ni:0.08, Mo:0.04", True),
        Field("sy", 'Base yield strength σy, MPa', "800"),
        Field("ods", 'ODS_factor (yttria)', "1.5"),
    ], c_alloy),
    Calc("demarre", 'Kinetic', 'De Marre [5]: bullets, fragments', [
        Field("d", 'Caliber d, mm', "12.7"), Field("m", 'Mass m, g', "46"), Field("v", 'Velocity v, m/s', "880"),
        Field("al", 'Impact angle α, deg', "0"), Field("K", 'K (armor resistance 0.85–0.95)', "0.9"),
        Field("h", 'Plate thickness h, mm (for v limit)', "25"),
    ], c_demarre),
    Calc("tate", 'Kinetic', 'Tate–Alekseevskii [6]: APFSDS', [
        Field("L", 'Rod length L, mm', "680"), Field("v", 'Velocity v, m/s', "1575"),
        Field("rp", 'Projectile ρ, kg/m³', "18600"), Field("rt", 'Armor ρ, kg/m³', "7850"),
        Field("Yp", 'Core Yp, GPa', "1.2"), Field("Rt", 'Armor Rt, GPa', "5.0"),
    ], c_tate),
    Calc("jet", 'Shaped charge', 'Jet [7]: hydrodynamics', [
        Field("L", 'Jet length L, mm', "400"), Field("rj", 'Jet ρ (copper 8900), kg/m³', "8900"),
        Field("rt", 'Armor ρ, kg/m³', "7850"),
    ], c_jet),
    Calc("thermal", 'Thermal protection', 'Heating [8–10]: flux, ΔT, melting', [
        Field("alt", 'Altitude, km', "30"), Field("V", 'Velocity V, m/s', "2000"),
        Field("CH", "C_H (1e-4…1e-3)", "0.0005"), Field("A", 'Heated area A, m²', "0.5"),
        Field("t", 'Time t, s', "30"), Field("m", 'Part mass m, kg', "20"),
        Field("el", 'Element material (Ti, Fe, W…) or blank', "", True),
        Field("c", 'c, J/(kg·K) (if blank above)', "523"), Field("T0", 'Initial T, °C', "20"),
        Field("Tm", 'Melting T, °C', "1668"), Field("Hf", 'Heat of fusion, kJ/kg', "295"),
    ], c_thermal),
    Calc("strength", 'Strength', 'von Mises, margin, weld [11–13]', [
        Field("s1", 'σ1, MPa', "300"), Field("s2", 'σ2, MPa', "100"), Field("s3", 'σ3, MPa', "0"),
        Field("sy", 'Yield strength σy, MPa', "500"), Field("nreq", 'Required margin n (aviation 1.2–1.5, tank 2.0)', "2.0"),
        Field("Kw", 'K_weld (TIG 0.85–0.95, laser 0.95–1.0)', "0.9"),
    ], c_strength),
    Calc("mass", 'Armor', 'Mass per 1 m² [14]', [
        Field("rho", 'Density, kg/m³', "7850"), Field("h", 'Thickness, mm', "50"), Field("A", 'Area, m²', "1"),
    ], c_mass),
    Calc("equiv", 'Armor', 'Composite equivalent [15]', [
        Field("layers", 'Layers: "thickness mm/σB MPa", comma-separated', "10/1500, 20/900, 5/400", True),
        Field("sst", 'Reference steel σB, MPa', "1000"),
    ], c_equiv),
    Calc("energy", 'Kinetic', 'Impact energy [16]', [
        Field("m", 'Mass m, g', "4000"), Field("v", 'Velocity v, m/s', "1575"),
    ], c_energy),
    Calc("pressure", 'Kinetic', 'Impact pressure [17]', [
        Field("mp", 'Projectile material (Fe, W, Cu, U…)', "W", True), Field("mt", 'Target material', "Fe", True),
        Field("v", 'Velocity v, m/s', "1500"),
    ], c_pressure),
    Calc("impedance", 'Waves', 'Acoustic impedance [14]', [
        Field("r1", 'Layer 1 density ρ1, kg/m³', "7850"), Field("c1", 'Layer 1 sound speed c1, m/s', "5000"),
        Field("r2", 'Layer 2 density ρ2, kg/m³', "1100"), Field("c2", 'Layer 2 sound speed c2, m/s', "1500"),
    ], c_impedance),
]
CALC_BY_KEY = {c.key: c for c in CALCS}


def run(key, values):
    """Run the calculator; input errors -> a line with the reason."""
    c = CALC_BY_KEY[key]
    try:
        return c.fn(values)
    except ValueError as e:
        msg = str(e)
        if "could not convert" in msg or "invalid literal" in msg:
            msg = 'non-numeric value in a numeric field (%s)' % msg.split(":")[-1].strip()
        return ['Input error: %s' % msg]
    except KeyError as e:
        return ['Input error: unknown key %s' % e]
    except ZeroDivisionError:
        return ['Error: division by zero, check the values']
    except OverflowError:
        return ['Error: values too large']
