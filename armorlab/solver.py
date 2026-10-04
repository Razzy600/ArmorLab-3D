"""Physics core: reduced-order penetration models.

Kinetic: Tate-Alekseevsky model (rod erosion + target resistance Rt).
Shaped charge: discrete jet (elements with different velocities), Bernoulli
hydrodynamics with strength, jet stretching and breakup, velocity cutoff.
These are reduced-dimension engineering models, not a hydrocode.

Modes:
  NORMAL   - coarse step, fast result, simple hole shape
  ADVANCED - fine time step, per-layer energy accounting, dynamic protection (ERA)
  ULTRA    - same + morphology: crater, lip, bulge, petals, plug, spall
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
import numpy as np

from . import hyper as HYPER
from .data import (MATERIALS, CORES, AMMO, ERA_KEY, ERA_FLYER_V, CU_RHO, CU_Y,
                   rod_mass)

MODES = ("NORMAL", "ADVANCED", "ULTRA")
RAD = math.pi / 180.0


@dataclass
class Layer:
    mat: str
    t: float            # normal thickness, m
    angle: float = 0.0  # angle from normal, deg
    gap: float = 0.0    # air gap behind the layer along the line of fire, m
    w: float = 0.0      # plate width, m (0 = auto); diameter for a round plate
    h: float = 0.0      # plate height, m (0 = auto)
    shape: str = "rect"  # rect | round
    ou: float = 0.0     # offset of the plate center from the line of fire along the tilt, m
    ov: float = 0.0     # horizontal offset of the plate center, m
    dmg: float = 0.0    # accumulated layer damage D 0..1 (multiple hits)
    dth: float = 0.0    # thermal part of damage D (already included in dmg; needed for synergy with impact)


def auto_half(t, angle, dc):
    """Automatic plate half-size, m (dc - characteristic projectile size)."""
    base = max(0.09, 4.5 * dc)
    return max(base, 1.15 * t * math.tan(min(angle, 80) * math.pi / 180) + 0.07 + 2.5 * dc)


def plate_geom(l, dc):
    """Plate geometry relative to the impact point. Returns a dict."""
    a = auto_half(l.t, l.angle, dc)
    W = l.w if l.w > 0 else 2 * a
    Hh = l.h if l.h > 0 else 2 * a
    g = dict(shape=l.shape, W=W, Hh=Hh, ou=l.ou, ov=l.ov)
    m = 0.004
    if l.shape == "round":
        R = W / 2
        g["R"] = R
        g["hit"] = math.hypot(l.ou, l.ov) < R - m
    else:
        g["ul"] = Hh / 2 - l.ou
        g["ur"] = Hh / 2 + l.ou
        g["vd"] = W / 2 - l.ov
        g["vu"] = W / 2 + l.ov
        g["hit"] = min(g["ul"], g["ur"], g["vd"], g["vu"]) > m
    return g


@dataclass
class Slab:
    mat: str
    t: float
    angle: float
    gap: float
    parent: int
    role: str = "plate"     # plate | flyer | witness
    era_group: int = -1
    miss: bool = False
    T: float = 0.0          # path length along the line of fire
    s_front: float = 0.0
    dmg: float = 0.0        # layer damage D (for the ceramic effect)


@dataclass
class Hole:
    k: np.ndarray                   # fraction of normal thickness 0..kmax
    r: np.ndarray                   # hole radius, m (in-plane, before stretching by tilt)
    lip: float = 0.0                # lip height at the entry
    dish: float = 0.0               # dishing around the crater
    bulge: float = 0.0              # bulge on the rear face
    bulge_r: float = 0.0
    petals: int = 0
    petal_len: float = 0.0
    plug: bool = False
    cone: bool = False
    delam: bool = False
    ricochet: bool = False
    perforated: bool = False


@dataclass
class SlabRes:
    parent: int
    mat: str
    role: str
    t: float
    angle: float
    T: float
    s_front: float
    depth: float = 0.0
    perforated: bool = False
    mode: str = ""
    v_in: float = 0.0
    v_out: float = 0.0
    L_in: float = 0.0
    L_out: float = 0.0
    e_abs: float = 0.0
    plug_mass: float = 0.0
    plug_v: float = 0.0
    spall_n: int = 0
    spall_v: float = 0.0
    spall_mass: float = 0.0
    spall_area: float = 0.0
    spall_rv: float = -1.0   # fragment velocity after the spall liner (-1: not computed)
    spall_rm: float = 0.0    # mass of fragments that got behind the armor
    hole: Hole | None = None
    notes: list = field(default_factory=list)
    era_active: bool = False
    t_hit: float = 0.0
    t_exit: float = 0.0


@dataclass
class Result:
    ammo: str
    mode: str
    cls: str
    slabs: list
    verdict: str = ""
    v_res: float = 0.0
    L_res: float = 0.0
    witness_depth: float = 0.0
    witness_through: bool = False
    free_depth: float = 0.0
    rhae: float = 0.0
    e0: float = 0.0
    e_res: float = 0.0
    track: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    ricochet: bool = False
    ric_dir: tuple = (0, 0, 0)
    ric_v: float = 0.0
    standoff: float = 0.0
    t_end: float = 0.0
    jet: dict = field(default_factory=dict)
    stack_end: float = 0.0
    solve_ms: float = 0.0
    damage: list = field(default_factory=list)   # layer damage D after the shot
    dth: list = field(default_factory=list)      # thermal part (for synergy)
    pre: dict = field(default_factory=dict)      # precursor result (tandem)
    cond: dict = field(default_factory=dict)     # calculation conditions
    imp: list = field(default_factory=list)      # acoustic boundaries
    warns: list = field(default_factory=list)    # warnings about conditions


def _clamp(x, a, b):
    return a if x < a else b if x > b else x


# ----------------------------------------------------------------------------
# Tate equation
# ----------------------------------------------------------------------------
_RIC_BASE = [None]        # base ricochet threshold angle, ° (default 62), from cond['ric_base']
_SHARP_OVERRIDE = [None]   # set from cond['sharp'] for the duration of solve()


def tate(v, rho_p, rho_t, Yp, Rt):
    """Returns (u, erosion_rate, regime).
    u - penetration velocity, erosion_rate - rod shortening rate,
    regime: 'rigid' | 'erode' | 'dwell'."""
    if v <= 0:
        return 0.0, 0.0, "dwell"
    if Rt <= Yp:
        vr2 = 2.0 * (Yp - Rt) / rho_t
        if v * v <= vr2:
            return v, 0.0, "rigid"
    else:
        vc2 = 2.0 * (Rt - Yp) / rho_p
        if v * v <= vc2:
            return 0.0, v, "dwell"
    a = 0.5 * (rho_p - rho_t)
    b = -rho_p * v
    c = 0.5 * rho_p * v * v + Yp - Rt
    if abs(a) < 1e-6:
        u = -c / b
    else:
        disc = b * b - 4 * a * c
        if disc < 0:
            return 0.0, v, "dwell"
        sq = math.sqrt(disc)
        r1 = (-b - sq) / (2 * a)
        r2 = (-b + sq) / (2 * a)
        cand = [x for x in (r1, r2) if -1e-9 <= x <= v + 1e-9]
        u = min(cand) if cand else 0.0
        if len(cand) == 2 and a > 0:
            u = min(cand)
    u = _clamp(u, 0.0, v)
    return u, v - u, "erode"


# ----------------------------------------------------------------------------
# Plate preparation
# ----------------------------------------------------------------------------
def expand_layers(layers, theta_add, kobl, witness, witness_gap, witness_t=0.8, dc=0.02):
    slabs = []
    egrp = 0
    for i, l in enumerate(layers):
        miss = not plate_geom(l, dc)["hit"]
        if l.mat == ERA_KEY and l.dmg >= 0.99:                              # ERA has already fired: flyer plates exist, but "missed"
            tf = _clamp(0.12 * l.t, 0.002, 0.008)
            e = max(l.t - 2 * tf, 0.001)
            slabs.append(Slab("RHA", tf, l.angle, e, i, "flyer", egrp, True))
            slabs.append(Slab("RHA", tf, l.angle, l.gap, i, "flyer", egrp, True))
            egrp += 1
        elif l.mat == ERA_KEY:
            tf = _clamp(0.12 * l.t, 0.002, 0.008)
            e = max(l.t - 2 * tf, 0.001)
            c = max(math.cos((l.angle + theta_add) * RAD), 0.2)
            slabs.append(Slab("RHA", tf, l.angle, e / c, i, "flyer", egrp, miss))
            slabs.append(Slab("RHA", tf, l.angle, l.gap, i, "flyer", egrp, miss))
            egrp += 1
        else:
            slabs.append(Slab(l.mat, l.t, l.angle, l.gap, i, miss=miss, dmg=l.dmg))
    if witness:
        if slabs:
            slabs[-1].gap = max(slabs[-1].gap, 0.0)
        slabs.append(Slab("RHA", witness_t, 0.0, 0.0, len(layers), "witness"))
        if len(slabs) > 1:
            slabs[-2].gap = witness_gap
    pos = 0.0
    for s in slabs:
        c = max(math.cos((s.angle + (theta_add if s.role != "witness" else 0.0)) * RAD), 0.2)
        s.T = 0.0 if s.miss else s.t / (c ** kobl)
        s.s_front = pos
        pos += s.T + s.gap
    return slabs


def _backing_factor(slabs, i):
    """Ceramic needs a dense backing directly behind it."""
    m = MATERIALS[slabs[i].mat]
    if m.kind != "ceramic":
        return 1.0
    if i + 1 < len(slabs):
        nxt = slabs[i + 1]
        mm = MATERIALS[nxt.mat]
        if mm.rho > 2500 and mm.kind == "metal" and nxt.t >= 0.003 and slabs[i].gap < 0.01:
            return 1.0
    return 0.5


# ----------------------------------------------------------------------------
# Morphology
# ----------------------------------------------------------------------------
def _mode_name(mat, ammo, T, d, perforated, depth, plug, cone, delam, petals, ric):
    m = MATERIALS[mat]
    if ric:
        return 'ricochet, groove'
    if not perforated:
        if m.kind == "elastomer":
            return 'elastic absorption'
        if m.kind == "ceramic":
            return 'ceramic fracture, stopped'
        if m.kind == "composite":
            return 'delamination, stopped'
        if depth / max(T, 1e-9) > 0.75:
            return 'crater with rear bulge (penetration limit)'
        return 'crater, projectile stopped'
    if plug:
        return 'plugging'
    if petals:
        return 'petals (petaling)'
    if cone:
        return 'ceramic cone spall'
    if delam:
        return 'delamination and fiber pull-out'
    if m.kind == "concrete":
        return 'crater and through breach'
    return 'plastic hole expansion'


def make_hole(mat, ammo, T, t, theta, r_rod, v, depth, perforated, d,
              ultra, jet_r=None, seed=1):
    """Hole profile. r(k): radius as a function of the fraction of normal thickness."""
    m = MATERIALS[mat]
    rng = np.random.default_rng(seed)
    depth = max(min(depth, T), 1e-6)
    kmax = _clamp(depth / T, 1e-4, 1.0)
    n = 40
    kk = np.linspace(0.0, kmax, n)
    x = kk * T                    # path along the line of fire
    ev = _clamp(v / 1600.0, 0.3, 1.5)
    if jet_r is not None:
        r_tun = max(jet_r[1], 0.0006)
        r_ent = max(jet_r[0], r_tun * 1.2)
        rr = r_tun + (r_ent - r_tun) * np.exp(-x / max(0.4 * T, 1e-4))
        rr = np.maximum(rr, 0.0004)
    else:
        r_tun = r_rod * (1.15 + 0.35 * ev)
        a_ent = {"metal": 1.9, "ceramic": 2.3, "composite": 1.7, "elastomer": 1.0, "concrete": 3.0}[m.kind]
        r_ent = r_rod * a_ent * (0.8 + 0.2 * ev)
        L_c = max(3.0 * d, 1e-4)
        rr = r_tun + (r_ent - r_tun) * np.exp(-x / L_c)
        if m.kind == "ceramic":
            rr = rr + np.tan(25 * RAD) * x * 0.8
        if m.kind == "concrete":
            rr = rr + np.tan(18 * RAD) * x
        if m.kind == "elastomer":
            rr = rr * 0.35
    hole = Hole(k=kk, r=rr.copy(), perforated=perforated)
    if not perforated:
        # rounded crater bottom
        rb = max(rr[-1], 1e-4)
        L_b = min(rb * 1.1, x[-1] * 0.8 if x[-1] > 0 else rb)
        mask = x > x[-1] - L_b
        if mask.any():
            q = (x[mask] - (x[-1] - L_b)) / max(L_b, 1e-9)
            hole.r[mask] = rr[mask] * np.sqrt(np.clip(1 - q * q, 0, 1))
        hole.r[-1] = 0.0
    tau = T / max(d, 1e-6)
    if ultra:
        hole.lip = 0.35 * r_rod * (0.5 + ev * 0.5) if m.kind == "metal" else 0.0
        hole.dish = 0.25 * r_rod
        if not perforated:
            rem = 1.0 - kmax
            if rem < 0.45 and m.kind in ("metal", "composite", "elastomer"):
                # rear bulge: height is limited (a thick plate does not bulge tens of centimeters), width is a shallow dome
                Ls = min(t, max(8.0 * r_tun, 0.05))
                hole.bulge = min((0.45 - rem) * Ls * 0.9, 0.04)
                hole.bulge_r = _clamp(0.25 * t, max(3.0 * r_tun, 0.02), 0.12)
            if m.kind == "composite":
                hole.delam = True
                hole.bulge = min(max(hole.bulge, 0.15 * t), 0.04)
                hole.bulge_r = _clamp(0.3 * t, max(5.0 * r_tun, 0.03), 0.15)
        else:
            blunt = ammo.nose == "blunt" if ammo else False
            if m.kind == "metal":
                if blunt and tau < 1.3 and m.spall > 0.3:
                    hole.plug = True
                    hole.r[:] = r_rod * 1.1
                    hole.lip = 0.0
                elif tau < 0.9 and jet_r is None:
                    hole.petals = int(rng.integers(5, 8))
                    hole.petal_len = r_rod * (1.0 + 1.5 * (1 - min(tau, 0.9)))
                    hole.r[-4:] = hole.r[-4:] * 0.9
            elif m.kind == "ceramic":
                hole.cone = True
            elif m.kind == "composite":
                hole.delam = True
                hole.bulge = 0.1 * T
                hole.bulge_r = max(4 * r_tun, 0.03)
    return hole


# ----------------------------------------------------------------------------
# Rods and bullets
# ----------------------------------------------------------------------------
class _Rec:
    def __init__(self):
        self.t, self.s, self.L, self.v, self.i = [], [], [], [], []

    def add(self, t, s, L, v, i):
        self.t.append(t); self.s.append(s); self.L.append(L); self.v.append(v); self.i.append(i)


# spall liner energy absorption, J per kg of material (estimate from FSP ballistic tests, order of magnitude)
_LINER_SEA = {"ARAMID": 8000.0, "UHMWPE": 10000.0}


def _apply_spall_liners(res_slabs):
    """Spall fragments fly into the layers behind the armor. Soft layers (aramid, PE, rubber) absorb energy
    in proportion to the mass under the fragment cloud, metals - by the work of displacing material by the fragments."""
    for j, src in enumerate(res_slabs):
        if src.spall_n <= 0 or src.role == "witness":
            continue
        m = src.spall_mass
        v = src.spall_v
        E0 = 0.5 * m * v * v
        E = E0
        src_rho = MATERIALS[src.mat].rho
        absorbed = []
        for k in range(j + 1, len(res_slabs)):
            ab = res_slabs[k]
            jet_hole = ab.perforated and ab.mode.startswith('shaped-charge channel')
            if ab.role in ("witness", "flyer") or ab.mode == 'missed plate' or (ab.perforated and not jet_hole):
                continue
            if jet_hole:
                frac = 0.8     # the jet channel is narrow: the rest of the plate area is intact and catches fragments
            else:
                frac = 1.0 - min(ab.depth / ab.T, 1.0) if ab.T > 0 else 1.0   # part of the layer not damaged by the rod
            if frac < 0.05:
                continue
            if E <= 1.0:
                break
            am = MATERIALS[ab.mat]
            if am.kind in ("composite", "elastomer"):
                bk = ab.mat.split("~")[0]
                sea = _LINER_SEA.get(bk, 6000.0 if am.kind == "composite" else 1500.0)
                if "~" in ab.mat and bk in MATERIALS and MATERIALS[bk].rt_gpa > 0:
                    sea *= _clamp(am.rt_gpa / MATERIALS[bk].rt_gpa, 0.2, 1.0)      # heating/degradation reduce absorption
                a_eff = max(src.spall_area, src.spall_n * 0.003, 1e-6)   # area over which the cloud spreads
                cap = sea * am.rho * ab.t * a_eff
            elif am.kind == "metal":
                nfr = max(src.spall_n, 1)
                a_f = nfr * (m / nfr / src_rho) ** (2.0 / 3.0)
                cap = am.rt_gpa * 1e9 * a_f * ab.t
            else:
                cap = 0.0
            e_abs = min(E, cap * frac)
            if e_abs > 0:
                ab.notes.append('absorbs spall fragments: %.1f of %.1f kJ' % (e_abs / 1000, E / 1000))
                if not ab.mode:
                    ab.mode = 'spall liner'
                absorbed.append(ab.mat)
            E -= e_abs
        if absorbed:
            if E < 0.02 * E0:
                src.spall_rv, src.spall_rm = 0.0, 0.0
            else:
                src.spall_rv = math.sqrt(2.0 * E / max(m, 1e-9))
                src.spall_rm = m
        else:
            src.spall_rv, src.spall_rm = v, m


def _solve_rod(ammo, v0, layers, yaw, mode, witness, witness_gap, rec=True):
    res_slabs = []
    core = CORES[ammo.core]
    rho_p, Yp = core.rho, core.yield_gpa * 1e9
    sharp_k = _SHARP_OVERRIDE[0] if _SHARP_OVERRIDE[0] is not None else core.sharp
    d = ammo.d_mm / 1000.0
    r = d / 2
    A = math.pi * r * r
    L0 = ammo.L_mm / 1000.0
    kobl = 0.9 if ammo.nose == "pointed" else 1.0
    slabs = expand_layers(layers, yaw, kobl, witness, witness_gap, dc=d)
    dt0 = {"NORMAL": 4e-6, "ADVANCED": 0.5e-6, "ULTRA": 0.2e-6}[mode]
    sample_dt = 1.5e-6
    track = _Rec()
    events = []
    L, v = L0, v0
    t = 0.0
    last_sample = -1.0
    Lmin = max(0.06 * d, 1e-4)
    vmin_stop = 40.0
    ric = False
    ric_dir = (0, 0, 0)
    ric_v = 0.0
    e0 = 0.5 * rho_p * A * L0 * v0 * v0
    stopped = False
    th_r = (_RIC_BASE[0] if _RIC_BASE[0] is not None else 62.0) + 12 * min((L0 / d) / 20.0, 1.0) + 8 * min(v0 / 1600.0, 1.2)
    era_active_group = {}
    s = 0.0
    if rec:
        track.add(0.0, 0.0, L, v, -1)
    for j, sl in enumerate(slabs):
        mat = MATERIALS[sl.mat]
        sr = SlabRes(sl.parent, sl.mat, sl.role, sl.t, sl.angle, sl.T, sl.s_front)
        res_slabs.append(sr)
        if stopped:
            sr.notes.append('not reached')
            continue
        # flight across the gap to the layer
        if j > 0:
            g = sl.s_front - s
            if g > 1e-9:
                dt = g / max(v, 1.0)
                t += dt
                s = sl.s_front
                if rec:
                    track.add(t, s, L, v, -1)
        sr.v_in, sr.L_in = v, L
        sr.t_hit = t
        if sl.miss:
            sr.perforated = True
            sr.mode = 'missed plate'
            sr.v_out, sr.L_out = v, L
            sr.t_exit = t
            continue
        thf = sl.angle + (yaw if sl.role != "witness" else 0.0)
        # ricochet
        if sl.role != "witness" and thf > th_r:
            ric = True
            a = sl.angle * RAD
            n = (-math.cos(a), 0.0, math.sin(a))
            dd = n[0]  # d=(1,0,0)
            od = (1 - 2 * dd * n[0], -2 * dd * n[1], -2 * dd * n[2])
            ric_dir = od
            ric_v = 0.45 * v
            sr.perforated = False
            sr.depth = 0.2 * d
            sr.mode = 'ricochet, groove'
            sr.hole = make_hole(sl.mat, ammo, sl.T, sl.t, a, r, v, sr.depth, False, d, mode == "ULTRA")
            sr.hole.ricochet = True
            sr.hole.k = sr.hole.k * 0.2
            sr.v_out, sr.L_out = ric_v, L
            events.append(dict(t=t, kind="ricochet", slab=j, s=s))
            stopped = True
            sr.t_exit = t
            if rec:
                track.add(t, s, L, v, j)
            continue
        # dynamic protection (ERA)
        mult = 1.0
        if sl.role == "flyer":
            g = sl.era_group
            if g not in era_active_group:
                act = v > 700.0
                era_active_group[g] = act
                if act:
                    events.append(dict(t=t, kind="era", slab=j, s=s, group=g, parent=sl.parent))
                    if mode != "NORMAL":
                        cut = _clamp(0.28 * (2 * sl.t / max(math.cos(thf * RAD), 0.2)) / d, 0, 0.35)
                        if core.brittle:
                            cut = min(cut * 2, 0.6)
                        L *= (1 - cut)
                        sr.notes.append('ERA cuts %d%% of length' % int(cut * 100))
            sr.era_active = era_active_group[g]
            if era_active_group[g] and mode != "NORMAL":
                mult = 1.35
        T = sl.T * mult
        Rt = mat.rt_gpa * 1e9 * _backing_factor(slabs, j) * (0.45 if ammo.cls == "ap" else 1.0)
        # brittle fracture of the core
        if core.brittle:
            f = 0.55 * math.sin(thf * RAD) ** 1.5 + (0.15 if mat.kind == "ceramic" or mat.key == "HHS" else 0.0)
            if sl.role == "witness":
                f = 0.0
            if f > 0.02:
                L *= (1 - min(f, 0.7))
                sr.notes.append('core fragments (%d%%)' % int(100 * min(f, 0.7)))
        depth = 0.0
        L_before = L
        perforated = False
        eroded_len = 0.0
        guard = 0
        while True:
            guard += 1
            if guard > 200000:
                break
            if L < Lmin or v < vmin_stop:
                stopped = True
                break
            u, er, reg = tate(v, rho_p, mat.rho, Yp, Rt)
            if reg == "erode" and sharp_k > 0:        # self-sharpening: narrow channel, less loss to mushrooming
                u = min(u * (1.0 + sharp_k), 0.98 * v)
                er = v - u
            if reg == "rigid":
                decel = (0.5 * mat.rho * v * v + Rt) / (rho_p * L)
            else:
                decel = Yp / (rho_p * L)
            dt = dt0
            if mode == "NORMAL":
                if er > 0:
                    dt = min(dt, 0.04 * L / er)
                dt = min(dt, 0.04 * v / max(decel, 1e-6))
            if u > 0:
                dt = min(dt, (T - depth) / u + 1e-13)
            dt = max(dt, 2e-9)
            depth += u * dt
            L -= er * dt
            eroded_len += er * dt
            v -= decel * dt
            t += dt
            if rec and t - last_sample >= sample_dt:
                track.add(t, sl.s_front + min(depth / mult, sl.T), L, v, j)
                last_sample = t
            if depth >= T - 1e-9:
                perforated = True
                break
        sr.depth = min(depth / mult, sl.T)
        s = sl.s_front + sr.depth
        sr.perforated = perforated
        sr.t_exit = t
        v = max(v, 0.0)
        sr.v_out, sr.L_out = v, max(L, 0.0)
        e_in = 0.5 * rho_p * A * sr.L_in * sr.v_in ** 2
        e_out = 0.5 * rho_p * A * max(L, 0) * v * v if perforated else 0.0
        sr.e_abs = e_in - e_out
        if rec:
            track.add(t, s, max(L, 0), v, j)
        # erosion particles
        if sl.role != "flyer" and eroded_len > 0:
            n = int(_clamp(25 * eroded_len / d, 8, 420))
            events.append(dict(t=sr.t_hit, t2=t, kind="splash", slab=j, s=sl.s_front, n=n, v=sr.v_in))
        # morphology and secondary effects
        if sl.role != "flyer":
            ult = mode == "ULTRA"
            sr.hole = make_hole(sl.mat, ammo, sl.T, sl.t, sl.angle * RAD, r, sr.v_in,
                                sr.depth, perforated, d, ult, seed=j + 7)
            tau = sl.T / d
            if sr.hole.plug:
                sr.plug_mass = mat.rho * math.pi * (1.1 * r) ** 2 * sl.t
                sr.plug_v = 0.7 * v
                events.append(dict(t=t, kind="plug", slab=j, s=s, v=sr.plug_v))
            # behind-armor spall: estimate from the energy absorbed by the layer (model assumption, not an experiment)
            remf = 1.0 - sr.depth / sl.T if sl.T > 0 else 0.0
            thr = 0.30 + 0.20 * mat.spall
            sev = 1.0 if perforated else max(0.0, 1.0 - remf / thr)
            if mode != "NORMAL" and mat.spall > 0.05 and sev > 0.0 and sl.role != "witness":
                t_s = min(max(sl.T - sr.depth, 0.5 * d), 1.5 * d) if not perforated else 0.5 * d
                m_sp = mat.rho * math.pi * (r + t_s) ** 2 * t_s
                en = (e_out / max(e_in, 1.0)) if perforated else 0.0
                # a ductile matrix damps the reflected-wave peak: the higher σ_spall, the weaker the spall (assumption, baseline 1.5 GPa)
                damp = _clamp(1.5 / mat.spall_gpa, 0.3, 1.0) if mat.spall_gpa > 0 else 1.0
                e_sp = (0.02 + 0.03 * en) * mat.spall * sev * max(sr.e_abs, 0.0) * damp
                v_sp = min(math.sqrt(2.0 * e_sp / max(m_sp, 1e-9)), 0.3 * max(sr.v_in, 1.0))
                if perforated:
                    n = int(_clamp(mat.spall * (14 + 90 * en), 0, 90))
                else:
                    n = int(_clamp(10 + 30 * mat.spall * sev, 0, 60))
                m_fr = m_sp * min(1.0, 0.25 + 0.5 * sev) * damp * (1.0 if perforated else min(1.0, 2.0 * sev))   # spall smoothly → 0 as sev → 0
                if m_fr < DUST_MASS:      # anything below 1 g is treated as dust
                    n = 0
                if n and v_sp > 5.0 and (perforated or mode == "ULTRA" or sev > 0.3):
                    sr.spall_n = n
                    sr.spall_v = v_sp
                    sr.spall_mass = m_fr
                    sr.spall_area = math.pi * (r + t_s) ** 2
                    events.append(dict(t=t, kind="spall", slab=j, s=s, n=n, v=sr.spall_v))
            sr.mode = _mode_name(sl.mat, ammo, sl.T, d, perforated, sr.depth,
                                 sr.hole.plug, sr.hole.cone, sr.hole.delam, sr.hole.petals, False)
        else:
            sr.mode = 'flyer plate'
        if not perforated:
            stopped = True
    _apply_spall_liners(res_slabs)
    e_res = 0.0
    final_perf = (not stopped) and len(slabs) > 0
    out = dict(slabs=res_slabs, track=track, events=events, ric=ric, ric_dir=ric_dir,
               ric_v=ric_v, e0=e0, v=v, L=L, stopped=stopped, t=t, slab_defs=slabs)
    return out


# ----------------------------------------------------------------------------
# Shaped-charge jet
# ----------------------------------------------------------------------------
_JETCAL = {}


def _liner_mass(a):
    D = a.d_mm / 1000.0
    al = a.half_angle * RAD
    slant = (D / 2) / math.sin(al)
    return CU_RHO * (a.liner_mm / 1000.0) * math.pi * (D / 2) * slant


def _jet_profile(a, N):
    xi_e = np.linspace(0, 1, N + 1)
    ve = a.vmin + (a.vt - a.vmin) * (1 - xi_e) ** 1.6
    v = 0.5 * (ve[:-1] + ve[1:])
    dv = ve[:-1] - ve[1:]
    return v, dv


DUST_MASS = 0.001   # kg: fragments lighter than this are treated as dust


# Effect of ceramic on the shaped-charge jet (empirical coherence model; assumption, not a measurement)
JET_CERAMIC_EFFECT = True


# ERA against the jet (assumptions): detonation when the jet energy exceeds a threshold; plates cut the jet:
# loss fraction = ERA_CUT * s(angle) * growth(time after firing), s = min(1, 0.4 + 0.6 sin(plate angle))
ERA_DET_E = 50e3      # J, initiation threshold on jet energy
ERA_CUT = 0.85        # maximum loss of length/coherence of a jet element
ERA_RAMP = 4e-6       # s, effect ramp-up time after firing


def era_disruption(angle_deg, dt):
    s = min(1.0, 0.4 + 0.6 * math.sin(math.radians(min(max(angle_deg, 0.0), 80.0))))
    ramp = min(max(dt / ERA_RAMP, 0.0), 1.0)
    return 1.0 - ERA_CUT * s * ramp


def ceramic_effect(jet_velocity, ceramic_thickness, caliber, gap_after=False, dmg=0.0):
    """Effect of a ceramic layer on a jet element that has passed completely through it.
    thickness_ratio = ceramic thickness / charge caliber.
    coherence = max(0.2, 1 - 0.4*ratio); an air gap after the ceramic reduces coherence by a further 30% (x0.7).
    velocity_drop = v*0.02*ratio; the length of the remaining element is multiplied by coherence."""
    ratio = ceramic_thickness / max(caliber, 1e-6)
    coh = max(0.2, 1.0 - 0.4 * ratio)
    if gap_after:
        coh *= 0.7
    coh = 1.0 - (1.0 - coh) * (1.0 - min(max(dmg, 0.0), 1.0))   # damaged ceramic disrupts coherence less effectively
    return dict(coherence=coh, velocity_drop=jet_velocity * 0.02 * ratio, jet_length_factor=coh, ratio=ratio)


def _jet_run(a, standoff, layers, mode, witness, witness_gap, lf, tb, N, rec=True, free=False):
    D = a.d_mm / 1000.0
    kobl = 1.0
    if free:
        slabs = [Slab("RHA", 3.0, 0.0, 0.0, 0, "witness")]
        pos = 0.0
        for s_ in slabs:
            s_.T = s_.t; s_.s_front = 0.0
    else:
        slabs = expand_layers(layers, 0.0, kobl, witness, witness_gap, witness_t=1.2, dc=0.35 * D)
    vj, dvj = _jet_profile(a, N)
    mj = 0.3 * _liner_mass(a) / N
    res_slabs = [SlabRes(s.parent, s.mat, s.role, s.t, s.angle, s.T, s.s_front) for s in slabs]
    depth = [0.0] * len(slabs)
    prof = [[] for _ in slabs]
    t_hit = [None] * len(slabs)
    t_ex = [0.0] * len(slabs)
    v_in = [0.0] * len(slabs)
    era_t = {}
    era_events = []
    jj = 0
    dd = 0.0
    track_t, track_s, track_v = [0.0], [0.0], [vj[0]]
    S = standoff
    ns = len(slabs)
    tail_i = N
    cer_noted = {}
    era_noted = {}
    coh_cum, vfac = 1.0, 1.0
    e_jet = [0.0] * len(slabs)
    coh_slab = {}
    e_init = float(np.sum(0.5 * mj * vj ** 2))
    lost = dict(breakup=0.0, coh=0.0, stop=0.0, exit=0.0)
    jet_exit_v = 0.0
    exit_len = 0.0
    for i in range(N):
        v = vj[i]
        if jj >= ns:
            exit_len += 1
            jet_exit_v = v
            lost["exit"] += 0.5 * mj * v * v
            continue
        xb = slabs[jj].s_front + dd
        t_i = (S + xb) / v
        l_nom = lf * dvj[i] * t_i
        eff = 1.0 if t_i <= tb else math.exp(-(t_i - tb) / (1.5 * tb))
        l = l_nom * eff
        if coh_cum < 1.0:
            l *= coh_cum
            v *= vfac
        e_el = 0.5 * mj * v * v
        lost["breakup"] += e_el * (1.0 - eff)
        e_el *= eff
        l0 = max(l, 1e-12)
        rj = math.sqrt(mj / (CU_RHO * math.pi * max(l_nom, 1e-9)))
        era_cut_g = set()
        if rec:
            track_t.append(t_i); track_s.append(xb); track_v.append(v)
        while l > 0 and jj < ns:
            sl = slabs[jj]
            if sl.miss:
                jj += 1
                dd = 0.0
                continue
            mat = MATERIALS[sl.mat]
            if t_hit[jj] is None:
                t_hit[jj] = t_i
                v_in[jj] = v
                coh_slab[jj] = coh_cum
            mult = 1.0
            if sl.role == "flyer":
                g = sl.era_group
                if g not in era_t:
                    era_t[g] = t_i
                    era_events.append(dict(t=t_i, kind="era", slab=jj, s=sl.s_front, group=g, parent=sl.parent))
                if mode != "NORMAL":
                    mult = _clamp(1 + 1.0 * (ERA_FLYER_V * (t_i - era_t[g])) / 0.01, 1.0, 8.0)
                if g not in era_cut_g and e_init >= ERA_DET_E:
                    era_cut_g.add(g)
                    fe = era_disruption(sl.angle, t_i - era_t[g])
                    if fe < 1.0:
                        lost["coh"] += e_el * l * (1.0 - fe) / l0
                        l *= fe
                        if fe < 0.5 and not era_noted.get(g):
                            era_noted[g] = True
                            res_slabs[jj].notes.append('ERA cuts the jet: loss of length/coherence up to %.0f%%' % (100 * (1 - fe)))
            Rj = mat.rj_gpa * 1e9 * _backing_factor(slabs, jj)
            u, er, reg = tate(v, CU_RHO, mat.rho, CU_Y * 1e9, Rj)
            if u <= 1e-3:
                lost["stop"] += e_el * l / l0
                l = 0.0
                break
            T = sl.T
            rem = (T - dd) * mult
            need = rem * er / u
            rh = max(rj * (1.6 + 3.2 * v / a.vt), 0.0008)
            if l >= need:
                l -= need
                e_jet[jj] += e_el * need / l0
                depth[jj] = T
                prof[jj].append((T, rh))
                t_ex[jj] = t_i
                if JET_CERAMIC_EFFECT and mat.kind == "ceramic" and sl.role != "flyer":
                    gap_after = (jj + 1 < ns and slabs[jj + 1].s_front - (sl.s_front + sl.T) > 1e-6)
                    ce = ceramic_effect(v, sl.T, D, gap_after, sl.dmg)
                    lost["coh"] += e_el * l * (1.0 - ce["jet_length_factor"]) / l0
                    l *= ce["jet_length_factor"]
                    v = max(v - ce["velocity_drop"], 0.3 * v)
                    # the channel in the ceramic is open: all following jet elements pass through "already damaged" ceramic
                    coh_cum *= ce["jet_length_factor"]
                    vfac *= max(1.0 - 0.02 * ce["ratio"], 0.3)
                    if not cer_noted.get(jj):
                        cer_noted[jj] = True
                        res_slabs[jj].notes.append('jet after ceramic: coherence %.2f%s' % (
                            ce["coherence"], ' (gap -30%)' if gap_after else ""))
                jj += 1
                dd = 0.0
            else:
                e_jet[jj] += e_el * l / l0
                dp = l * u / er / mult
                dd += dp
                depth[jj] = dd
                prof[jj].append((dd, rh))
                t_ex[jj] = t_i
                l = 0.0
        if jj >= ns:
            if l > 0:
                lost["exit"] += e_el * l / l0
            tail_i = i
    # per-plate results
    e_total = 0.0
    for j, sl in enumerate(slabs):
        sr = res_slabs[j]
        sr.depth = depth[j]
        sr.perforated = depth[j] >= sl.T - 1e-9
        sr.v_in = v_in[j]
        sr.t_hit = t_hit[j] or 0.0
        sr.t_exit = t_ex[j]
        sr.mode = 'missed plate' if sl.miss else 'flyer plate' if sl.role == "flyer" else (
            'shaped-charge channel, through' if sr.perforated else
            ('shaped-charge channel' if depth[j] > 0 else 'not reached'))
        sr.era_active = sl.role == "flyer" and sl.era_group in era_t
        if sl.role != "flyer" and depth[j] > 0:
            pts = prof[j]
            rs0 = pts[0][1]
            rs1 = pts[-1][1]
            ult = mode == "ULTRA"
            sr.hole = make_hole(sl.mat, a, sl.T, sl.t, sl.angle * RAD, rs1, v_in[j],
                                depth[j], sr.perforated, 2 * rs1, ult, jet_r=(rs0 * 1.0, rs1), seed=j + 3)
            if sr.perforated and mode != "NORMAL":
                m = MATERIALS[sl.mat]
                # fragment mass: volume of the destroyed zone at the channel exit * fragmentation fraction (ceramic 0.25, metal 0.08)
                kfr = 0.25 if m.kind == "ceramic" else 0.08
                damp = _clamp(1.5 / m.spall_gpa, 0.3, 1.0) if m.spall_gpa > 0 else 1.0
                r_s = 2.0 * rs1
                m_fr = m.rho * math.pi * r_s ** 2 * min(sl.T, 1.5 * r_s) * kfr * m.spall * damp
                if m_fr >= DUST_MASS and m.spall > 0.05:
                    sr.spall_n = int(_clamp(m.spall * 40, 1, 40))
                    sr.spall_v = 200.0
                    sr.spall_mass = m_fr
                    sr.spall_area = math.pi * r_s ** 2
    for j in range(len(slabs)):
        res_slabs[j].e_abs = e_jet[j]
    if coh_cum < 0.3 and not free:
        for j in range(len(slabs) - 1, -1, -1):
            if slabs[j].role != "witness" and res_slabs[j].mode.startswith('shaped-charge channel'):
                res_slabs[j].notes.append('jet coherence %.2f < 0.3: particle regime (accounted for by jet shortening)' % coh_cum)
                break
    e_slabs = float(sum(e_jet))
    if not free and mode != "NORMAL":
        _apply_spall_liners(res_slabs)
    out = dict(e_balance=dict(init=e_init, slabs=e_slabs, other=e_init - e_slabs - sum(lost.values()), coh_cum=coh_cum, **lost),
               slabs=res_slabs, slab_defs=slabs, track=(track_t, track_s, track_v), coh_slab=coh_slab,
               events=era_events, depth=depth, jet_len_cut=tail_i, jet_exit=(jet_exit_v, exit_len),
               through=(jj >= ns), t_end=track_t[-1], vj=vj, dvj=dvj, lf=lf, tb=tb)
    return out


def calibrate_jets():
    for key, a in AMMO.items():
        if a.cls != "heat":
            continue
        D = a.d_mm / 1000.0
        S = a.s_opt_cd * D
        tb = 1.4 * S / a.vt
        lo, hi = 0.02, 6.0
        for _ in range(36):
            mid = 0.5 * (lo + hi)
            o = _jet_run(a, S, [], "ADVANCED", False, 0.0, mid, tb, 60, rec=False, free=True)
            p = o["depth"][0]
            if p < a.rated_mm / 1000.0:
                lo = mid
            else:
                hi = mid
        _JETCAL[key] = (0.5 * (lo + hi), tb)


calibrate_jets()


# ----------------------------------------------------------------------------
# Top level
# ----------------------------------------------------------------------------
def free_rha_depth(ammo, v0, standoff, yaw=0.0, mode="ADVANCED"):
    """Penetration depth into semi-infinite RHA with no obstacles."""
    if ammo.cls == "heat":
        lf, tb = _JETCAL[ammo.key]
        o = _jet_run(ammo, standoff, [], mode, False, 0.0, lf, tb, 120, rec=False, free=True)
        return o["depth"][0]
    big = [Layer("RHA", 3.0, 0.0, 0.0)]
    o = _solve_rod(ammo, v0, big, 0.0, mode, False, 0.0, rec=False)
    return o["slabs"][0].depth


def _solve_core(ammo_key, v0, layers, mode="ADVANCED", yaw=0.0, standoff=0.5,
                witness=True, witness_gap=0.05):
    import time
    t0 = time.perf_counter()
    a = AMMO[ammo_key]
    if a.cls == "heat":
        lf, tb = _JETCAL[ammo_key]
        N = {"NORMAL": 40, "ADVANCED": 140, "ULTRA": 360}[mode]
        o = _jet_run(a, standoff, layers, mode, witness, witness_gap, lf, tb, N)
        slabs = o["slabs"]
        res = Result(ammo_key, mode, "heat", slabs)
        res.standoff = standoff
        tt, ss, vv = o["track"]
        res.track = dict(t=np.array(tt), s=np.array(ss), v=np.array(vv),
                         L=np.zeros(len(tt)), i=np.zeros(len(tt)))
        res.events = o["events"]
        res.t_end = o["t_end"]
        res.jet = dict(coh_slab=o["coh_slab"], e_bal=o["e_balance"], vt=a.vt, vmin=a.vmin, lf=lf, tb=tb, D=a.d_mm / 1000.0,
                       tail_cut=o["jet_len_cut"], through=o["through"])
        wl = slabs[-1] if (witness and slabs and slabs[-1].role == "witness") else None
        res.free_depth = free_rha_depth(a, v0, standoff, mode=mode)
        if wl is not None:
            res.witness_depth = wl.depth
            res.witness_through = wl.perforated
        n_real = len([s for s in slabs if s.role != "witness"])
        res.stack_end = o["slab_defs"][n_real - 1].s_front + o["slab_defs"][n_real - 1].T if n_real else 0.0
        stack_perf = all(s.perforated for s in slabs if s.role != "witness") if n_real else True
        res.verdict = 'PENETRATED' if stack_perf else 'STOPPED'
        if stack_perf and wl is not None:
            res.rhae = max(res.free_depth - wl.depth, 0.0)
        res.v_res = o["vj"][min(o["jet_len_cut"], len(o["vj"]) - 1)] if stack_perf else 0.0
        res.slab_defs = o["slab_defs"]
    else:
        o = _solve_rod(a, v0, layers, yaw, mode, witness, witness_gap)
        slabs = o["slabs"]
        res = Result(ammo_key, mode, a.cls, slabs)
        tr = o["track"]
        res.track = dict(t=np.array(tr.t), s=np.array(tr.s), L=np.array(tr.L),
                         v=np.array(tr.v), i=np.array(tr.i))
        res.events = o["events"]
        res.t_end = o["t"]
        res.ricochet = o["ric"]
        res.ric_dir = o["ric_dir"]
        res.ric_v = o["ric_v"]
        res.e0 = o["e0"]
        core = CORES[a.core]
        A = math.pi * (a.d_mm / 2000.0) ** 2
        wl = slabs[-1] if (witness and slabs and slabs[-1].role == "witness") else None
        real = [s for s in slabs if s.role != "witness"]
        stack_perf = all(s.perforated for s in real) if real else True
        res.free_depth = free_rha_depth(a, v0, 0.0, mode=mode)
        if o["ric"]:
            res.verdict = 'RICOCHET'
        elif stack_perf:
            res.verdict = 'PENETRATED'
        else:
            res.verdict = 'STOPPED'
        if wl is not None:
            res.witness_depth = wl.depth
            res.witness_through = wl.perforated
        if stack_perf and not o["ric"]:
            res.v_res = o["v"]
            res.L_res = max(o["L"], 0.0)
            res.e_res = 0.5 * core.rho * A * res.L_res * res.v_res ** 2
            if wl is not None:
                res.rhae = max(res.free_depth - wl.depth, 0.0)
            elif not real:
                res.rhae = 0.0
        res.slab_defs = o["slab_defs"]
        if real:
            last = o["slab_defs"][len(real) - 1]
            res.stack_end = last.s_front + last.T
    res.solve_ms = (time.perf_counter() - t0) * 1000
    return res


# ====================================================================== conditions, damage, tandem, impedance
# All coefficients below are assumptions set by the user (empirical), not test results.
_C_KIND = {"ceramic": 11000.0, "composite": 3500.0, "elastomer": 1500.0, "concrete": 3500.0}
_E_METAL_DEFAULT = 200.0


ELASTOMER_TG = -45.0      # °C, rubber glass-transition temperature (assumption)
ELASTOMER_GLASS_K = 3.8   # sound speed in glassy rubber is up to (1+K) times higher, modulus roughly 20+ times


# Thermal limit of elastomers, °C (assumption): above it the layer degrades (pyrolysis, charring), full degradation at +150 °C beyond it
ELASTOMER_TLIM = {"RUBBER": 150.0, "SILICONE": 250.0, "FKM": 300.0}
ELASTOMER_TLIM_DEFAULT = 150.0


def elastomer_degradation(key, temp):
    """0 - intact, 1 - fully charred."""
    lim = ELASTOMER_TLIM.get(key.split("~")[0], ELASTOMER_TLIM_DEFAULT)
    return min(max((temp - lim) / 150.0, 0.0), 1.0)


def elastomer_c_factor(temp):
    """Increase of sound speed in the elastomer on cooling: sigmoid around the glass-transition temperature."""
    x = (temp - ELASTOMER_TG) / 8.0
    sg = 1.0 / (1.0 + math.exp(min(max(x, -50.0), 50.0)))
    return 1.0 + ELASTOMER_GLASS_K * sg


def sound_speed(m, temp=20.0):
    if m.kind == "metal" or m.e_gpa > 0 and m.kind not in _C_KIND:
        return math.sqrt((m.e_gpa or _E_METAL_DEFAULT) * 1e9 / m.rho)
    c = _C_KIND.get(m.kind, 4000.0)
    if m.kind == "elastomer":
        c *= elastomer_c_factor(temp)      # E ~ rho*c^2: rubber stiffens in the cold
        c *= 1.0 + 2.5 * elastomer_degradation(m.key, temp)    # charred residue is brittle and stiff
    return c


def impedance(m, temp=20.0):
    """Acoustic impedance Z = rho*c, kg/(m2*s)."""
    return m.rho * sound_speed(m, temp)


Z_AIR = 1.2 * 340.0


def transmission(z1, z2):
    """Pressure transmission coefficient across a boundary: 4*Z1*Z2/(Z1+Z2)^2."""
    return 4.0 * z1 * z2 / (z1 + z2) ** 2


def condition_factors(m, temp=20.0, por=0.0, cycles=1.0, dmg=0.0, k_weld=1.0):
    """(rho_f, strength_f, spall_f) for the material under the given conditions."""
    rho_f, str_f, sp_f = 1.0, 1.0, 1.0
    if m.kind in ("metal", "ceramic") and por > 0:
        rho_f *= 1.0 - por
        str_f *= max(0.2, 1.0 - 2.0 * por)
    if cycles > 1 and m.kind in ("metal", "ceramic", "composite"):
        str_f *= cycles ** -0.1
    if m.kind == "metal":
        tm = m.tm_c if m.tm_c > 0 else 1500.0
        if temp > 20:
            str_f *= max(0.25, 1.0 - 0.75 * (temp - 20.0) / max(tm - 20.0, 1.0))
            if m.tm_c > 0 and temp + 273.0 > 0.4 * (m.tm_c + 273.0):
                str_f *= 0.9          # creep
        elif temp < 20:
            str_f *= min(1.15, 1.0 + 0.0015 * (20.0 - temp))
        if temp < -30 and m.key in ("HHS", "TI64"):
            sp_f *= 1.0 + min(1.0, (-30.0 - temp) / 50.0)     # cold brittleness: more spall
    elif m.kind == "ceramic" and temp > 1000:
        str_f *= max(0.3, 1.0 - (temp - 1000.0) / 1500.0)
    elif m.kind == "elastomer":
        if temp > 100:
            str_f *= max(0.4, 1.0 - (temp - 100.0) / 500.0)
        str_f *= 1.0 - 0.8 * elastomer_degradation(m.key, temp)     # thermal limit: pyrolysis
    elif m.kind == "composite" and temp > 200:
        str_f *= max(0.4, 1.0 - (temp - 200.0) / 600.0)
    if k_weld < 1.0 and m.kind == "metal":      # weld / HAZ: strength k, stronger spall (assumption: x(1+4(1-k)))
        str_f *= k_weld
        sp_f *= 1.0 + 4.0 * (1.0 - k_weld)
    if dmg > 0:
        str_f *= max(0.05, 1.0 - dmg)
        sp_f *= 1.0 + 0.5 * dmg
    return rho_f, str_f, sp_f


def material_variant(key, rho_f=1.0, str_f=1.0, sp_f=1.0):
    """Registers a derived material (key of the form BASE~...) and returns its key."""
    if key == ERA_KEY or key not in MATERIALS:
        return key
    if abs(rho_f - 1) < 1e-6 and abs(str_f - 1) < 1e-6 and abs(sp_f - 1) < 1e-6:
        return key
    base = key.split("~")[0]
    nk = "%s~%.4f_%.4f_%.4f" % (base, rho_f, str_f, sp_f)
    if nk not in MATERIALS:
        from dataclasses import replace
        m = MATERIALS[key]
        MATERIALS[nk] = replace(m, key=nk, rho=m.rho * rho_f, yield_gpa=m.yield_gpa * str_f, rt_gpa=m.rt_gpa * str_f,
                                rj_gpa=m.rj_gpa * str_f, spall=min(1.0, m.spall * sp_f), user=False)
    return nk


# Thermal shock (assumption): CTE mismatch of composite phases (not set by default; a material key can be added)
ALPHA_MISMATCH = {"SIC": 2.0e-6, "B4C": 2.0e-6, "AL2O3": 3.0e-6}   # assumption, order of magnitude
NU_POISSON = 0.3


# Synergy of thermal and impact damage (assumption): D = 1-(1-Dt)(1-Di) + k*Dt*Di, k: shock cracks as stress concentrators
SYNERGY_K = {}
SYNERGY_K_KIND = {"ceramic": 0.15, "composite": 0.1, "metal": 0.05, "elastomer": 0.0}


def synergy_k(mat_key, cond=None):
    if cond and cond.get("k_syn") is not None:
        return float(cond["k_syn"])
    base = mat_key.split("~")[0]
    if base in SYNERGY_K:
        return SYNERGY_K[base]
    m = MATERIALS.get(mat_key)
    return SYNERGY_K_KIND.get(m.kind if m else "metal", 0.05)


def thermal_shock_damage(m, t_from, t_to, alpha_f=1.0):
    """Damage D from thermal stresses: sigma = E*dAlpha*dT/(1-nu); D = 1.5*(sigma/sigma_y - 0.2), 0..0.5."""
    da = ALPHA_MISMATCH.get(m.key.split("~")[0], 0.0) * alpha_f
    if da <= 0 or m.e_gpa <= 0 or m.yield_gpa <= 0:
        return 0.0, 0.0
    sig = m.e_gpa * 1e9 * da * abs(t_from - t_to) / (1.0 - NU_POISSON)
    r = sig / (m.yield_gpa * 1e9)
    return min(max(1.5 * (r - 0.2), 0.0), 0.5), sig


def apply_conditions(layers, cond=None):
    cond = cond or {}
    temp = float(cond.get("temp", 20.0)); por = float(cond.get("por", 0.0)); cyc = float(cond.get("cycles", 1.0))
    t_pre = cond.get("t_pre")
    out = []
    for l in layers:
        if l.mat == ERA_KEY or l.mat not in MATERIALS:
            out.append(l)
            continue
        dm = l.dmg
        if t_pre is not None:
            dth, _ = thermal_shock_damage(MATERIALS[l.mat], float(t_pre), temp, float(cond.get("alpha_f", 1.0)))
            dm = 1.0 - (1.0 - dm) * (1.0 - dth)
        lt = cond.get("_lt")
        t_l = lt[len(out)] if (lt and len(out) < len(lt) and lt[len(out)] is not None) else temp
        rf, sf, spf = condition_factors(MATERIALS[l.mat], t_l, por, cyc, dm, float(cond.get("k_weld", 1.0)))
        nl = Layer(**{**l.__dict__})
        nl.mat = material_variant(l.mat, rf, sf, spf)
        out.append(nl)
    return out


def damage_after(res, layers, cond=None):
    """Accumulated damage D of each layer after the shot: D = 1-(1-D_prev)(1-D_new).
    D_new: ceramic 0.3+0.5*fraction (through 0.8), metal 0.2 (through) / 0.2*fraction, elastomer 0.3, composite 0.4 (assumptions)."""
    dn = [0.0] * len(layers)
    for s in res.slabs:
        i = s.parent
        if i >= len(layers) or s.role == "witness" or s.mode == 'missed plate':
            continue
        if s.role == "flyer":
            if s.era_active:
                dn[i] = 1.0
                for j in range(i + 1, len(layers)):      # the ERA fragment field slightly scratches the nearest layer behind it
                    if layers[j].mat != ERA_KEY:
                        dn[j] = max(dn[j], 0.05)
                        break
            continue
        if s.depth <= 0:
            continue
        frac = min(s.depth / s.T, 1.0) if s.T > 0 else 1.0
        m = MATERIALS.get(s.mat)
        kind = m.kind if m else "metal"
        if kind == "ceramic":
            d = 0.8 if s.perforated else 0.3 + 0.5 * frac
        elif kind == "elastomer":
            d = 0.3 if s.perforated else 0.25 * frac
        elif kind == "composite":
            d = 0.4 if s.perforated else 0.25 * frac
        else:
            d = 0.2 if s.perforated else 0.2 * frac
        dn[i] = max(dn[i], d)
    out = []
    for l, d in zip(layers, dn):
        D = 1.0 - (1.0 - l.dmg) * (1.0 - d)
        if l.dth > 0 and d > 0:
            D += synergy_k(l.mat, cond) * l.dth * d
        out.append(min(D, 1.0))
    return out


def _with_damage(layers, dmg):
    out = []
    for l, d in zip(layers, dmg):
        nl = Layer(**{**l.__dict__})
        nl.dmg = d
        out.append(nl)
    return out


def interface_report(layers, temp=20.0):
    """Acoustic boundaries between adjacent layers (along the line of fire)."""
    rows = []
    for i in range(len(layers) - 1):
        a, b = layers[i], layers[i + 1]
        if a.mat not in MATERIALS or b.mat not in MATERIALS:
            continue
        za = impedance(MATERIALS[a.mat], temp)
        if a.gap > 1e-6:
            rows.append((i, a.mat, 'air', transmission(za, Z_AIR)))
            continue
        zb = impedance(MATERIALS[b.mat], temp)
        rows.append((i, a.mat, b.mat, transmission(za, zb)))
    return rows


def _apply_hyper(res, a, v0, eff, witness_gap):
    """v > 3 km/s: replaces the Tate result with a Cour-Palais estimate + debris cloud (Whipple shield), see hyper.py."""
    idx = [i for i, s in enumerate(res.slabs) if s.role != "flyer"]
    plates = []
    for n, i in enumerate(idx):
        s = res.slabs[i]
        m = MATERIALS.get(s.mat) or MATERIALS.get(s.mat.split("~")[0])
        if m is None:
            return
        gap = eff[s.parent].gap if (s.role != "witness" and s.parent < len(eff)) else 0.0
        if n == len(idx) - 2 and idx and res.slabs[idx[-1]].role == "witness" and gap <= 0:
            gap = witness_gap
        plates.append((s.mat, s.T, gap, m.kind if m.kind == "elastomer" else ""))
    mats = {s.mat: (MATERIALS.get(s.mat) or MATERIALS.get(s.mat.split("~")[0])) for s in res.slabs}
    ev, passed = HYPER.run(a, CORES[a.core].rho, v0, plates, mats)
    for k, i in enumerate(idx):
        s = res.slabs[i]
        if k < len(ev):
            e = ev[k]
            s.depth, s.perforated, s.v_in, s.v_out = e["depth"], e["perf"], e["v_in"], e["v_out"]
            s.mode = 'hypervelocity'
            s.notes = [e["note"]]
            s.L_out = 0.0
        else:
            s.depth, s.perforated, s.v_in, s.v_out = 0.0, False, 0.0, 0.0
            s.mode, s.notes = 'not reached', ['not reached']
    res.verdict = 'PENETRATED' if passed else 'STOPPED'
    res.warns.append('hypervelocity regime (v=%.1f km/s): Cour-Palais + debris cloud, assumptions see hyper.py' % (v0 / 1000))


def solve(ammo_key, v0, layers, mode="ADVANCED", yaw=0.0, standoff=0.5,
          witness=True, witness_gap=0.05, cond=None):
    """Solver with environmental conditions (temperature, porosity, fatigue), layer damage and tandem warheads."""
    a = AMMO[ammo_key]
    cond = dict(cond or {})
    base_layers = [Layer(**{**l.__dict__}) for l in layers]
    heat = None
    if float(cond.get("heat_s", 0.0)) > 0:       # transient heating (1D): per-layer temperatures at the moment of impact
        from .thermal1d import layer_temps
        idx = [i for i, l in enumerate(layers) if l.mat != ERA_KEY and l.mat in MATERIALS]
        if idx:
            t_env = float(cond.get("t_env", cond.get("temp", 20.0)))
            tb, tl = layer_temps([(layers[i].mat, layers[i].t) for i in idx], t_env, float(cond["heat_s"]), 20.0, MATERIALS)
            lt = [None] * len(layers)
            for i, tv in zip(idx, tl):
                lt[i] = tv
            cond["_lt"] = lt
            heat = dict(t_env=t_env, seconds=float(cond["heat_s"]), t_back=tb, layer_T=lt)
    pre = {}
    if a.tandem and a.tandem in AMMO:
        pa = AMMO[a.tandem]
        pr = _solve_core(pa.key, pa.v, apply_conditions(base_layers, cond), mode, yaw, standoff, False, 0.0)
        dpre = damage_after(pr, base_layers)
        # the precursor is narrow (63 mm): its channel weakens the layers along the line but does not destroy them entirely
        dpre = [1.0 if (l.mat == ERA_KEY and d >= 0.99) else 0.6 * d for l, d in zip(base_layers, dpre)]
        base_layers = _with_damage(base_layers, [1.0 - (1.0 - l.dmg) * (1.0 - d) for l, d in zip(base_layers, dpre)])
        pre = dict(name=pa.name, verdict=pr.verdict,
                   depths=[(s.mat.split("~")[0], s.depth, s.T, s.perforated) for s in pr.slabs if s.role != "witness"],
                   dmg=dpre)
    # surface microcracks (surf, % of area, ~2 mm layer): D of the first layer += 0.01*surf (assumption)
    surf = float(cond.get("surf", 0.0))
    if surf > 0:
        for l in base_layers:
            if l.mat != ERA_KEY and l.mat in MATERIALS:
                l.dmg = max(l.dmg, min(0.01 * surf, 0.5))
                break
    eff = apply_conditions(base_layers, cond)
    # porosity as channels for the shaped-charge jet: h_eff = h(1-beta*P) (beta=por_beta, assumption, default 4; HEAT only)
    por_ch = float(cond.get("por", 0.0))
    if a.cls == "heat" and por_ch > 0:
        f_ch = max(0.5, 1.0 - float(cond.get("por_beta", 4.0)) * por_ch)
        for l in eff:
            if l.mat != ERA_KEY and l.mat in MATERIALS and MATERIALS[l.mat].kind != "elastomer":
                l.t *= f_ch
    _SHARP_OVERRIDE[0] = float(cond["sharp"]) if cond.get("sharp") is not None else None
    _RIC_BASE[0] = float(cond["ric_base"]) if cond.get("ric_base") is not None else None
    try:
        res = _solve_core(ammo_key, v0, eff, mode, yaw, standoff, witness, witness_gap)
    finally:
        _SHARP_OVERRIDE[0] = None
        _RIC_BASE[0] = None
    if cond.get("sharp") is not None and a.cls != "heat":
        res.warns.append('core self-sharpening: +%.0f%% to penetration velocity (empirical parameter)' % (100 * float(cond["sharp"])))
    if a.cls == "ap" and v0 >= HYPER.HV_V and a.core in CORES and cond.get("hyper", 1):
        _apply_hyper(res, a, v0, eff, witness_gap)
    if surf > 0:
        res.warns.append('surface cracks %.1f%%: D of the first layer not below %.3f' % (surf, min(0.01 * surf, 0.5)))
    if a.cls == "heat" and por_ch > 0:
        res.warns.append('porosity as channels: eff. thickness ×%.2f (β=%.1f)' % (f_ch, float(cond.get("por_beta", 4.0))))
    # thermal shock is a one-off event: its microdamage is included in the accumulated D (combined with impact damage)
    shock_layers = base_layers
    if cond.get("t_pre") is not None:
        tmp0 = float(cond.get("temp", 20.0))
        sl = []
        for l in base_layers:
            nl = Layer(**{**l.__dict__})
            if l.mat != ERA_KEY and l.mat in MATERIALS:
                dth, _ = thermal_shock_damage(MATERIALS[l.mat], float(cond["t_pre"]), tmp0, float(cond.get("alpha_f", 1.0)))
                nl.dmg = 1.0 - (1.0 - l.dmg) * (1.0 - dth)
                nl.dth = 1.0 - (1.0 - l.dth) * (1.0 - dth)
            sl.append(nl)
        shock_layers = sl
    res.damage = damage_after(res, shock_layers, cond)
    res.dth = [l.dth for l in shock_layers]
    d0 = damage_after(res, shock_layers, dict(cond, k_syn=0.0))
    for i, (da, db) in enumerate(zip(res.damage, d0)):
        if da - db > 0.001:
            res.warns.append('thermal+impact synergy, layer %d (%s): k=%.2f, +%.3f to D (%.2f → %.2f)' % (
                i + 1, shock_layers[i].mat.split("~")[0], synergy_k(shock_layers[i].mat, cond), da - db, db, da))
    res.pre = pre
    res.cond = cond
    res.heat = heat
    if heat:
        res.warns.append('heating %.0f °C, %.0f s (1D): layer T %s; rear %.0f °C' % (
            heat["t_env"], heat["seconds"], ", ".join("%d:%.0f" % (i + 1, t) for i, t in enumerate(heat["layer_T"]) if t is not None), heat["t_back"]))
    tmp = float(cond.get("temp", 20.0))
    if float(cond.get("k_weld", 1.0)) < 1.0:
        res.warns.append('weld/HAZ: strength of metal layers ×%.2f, spall ×%.2f' % (float(cond["k_weld"]), 1.0 + 4.0 * (1.0 - float(cond["k_weld"]))))
    if cond.get("t_pre") is not None:
        seen_t = set()
        for l in layers:
            m = MATERIALS.get(l.mat)
            if m is not None and l.mat not in seen_t:
                seen_t.add(l.mat)
                dth, sig = thermal_shock_damage(m, float(cond["t_pre"]), tmp, float(cond.get("alpha_f", 1.0)))
                if sig > 0:
                    res.warns.append('thermal shock %.0f→%.0f °C: %s σ_th=%.0f MPa (%.0f%% σy), microdamage D=%.2f' % (
                        float(cond["t_pre"]), tmp, l.mat, sig / 1e6, 100 * sig / (m.yield_gpa * 1e9), dth))
    seen = set()
    for l in layers:
        m = MATERIALS.get(l.mat)
        if m is not None and m.kind == "elastomer" and l.mat not in seen:
            seen.add(l.mat)
            dg = elastomer_degradation(l.mat, tmp)
            if dg > 0:
                res.warns.append('%s: above thermal limit by +%.0f °C, degradation %.0f%% (pyrolysis, charring)' % (
                    l.mat, ELASTOMER_TLIM.get(l.mat, ELASTOMER_TLIM_DEFAULT), 100 * dg))
    res.imp = interface_report(base_layers, float(cond.get("temp", 20.0)))
    for sr in res.slabs:
        sr.mat = sr.mat.split("~")[0]
    return res
