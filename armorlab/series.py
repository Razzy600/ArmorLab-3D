"""Hit series: area dispersion, a 2D damage grid with a gradient, crack transfer between layers.

All coefficients are assumptions (not measurements). The coordinate system is the plane perpendicular to the line of fire;
one grid is shared by all layers (parallax of inclined plates is not accounted for).
"""
import csv
import math
import os

import numpy as np

from . import solver as SV
from .data import AMMO, MATERIALS, ERA_KEY

GRID_N = 61          # cells per side
GRID_R = 0.30        # half-size of the field, m

# damage zone radius around the hit = ZONE[kind] * d_eff (d_eff: calibre; for shaped charges 0.35 * charge calibre)
ZONE = {"ceramic": 6.0, "composite": 3.5, "metal": 2.5, "elastomer": 3.0}
# crack transfer: source -> neighbouring layer (fraction), receiver susceptibility
CRACK_SRC = {"ceramic": 0.50, "metal": 0.25, "composite": 0.15, "elastomer": 0.0}
CRACK_TGT = {"ceramic": 1.0, "metal": 0.6, "composite": 0.8, "elastomer": 0.3}
ERA_TILE = 0.15      # ERA tile radius, m: a triggered block only affects its own zone (assumption)
GAP_BLOCK = 0.002    # an air gap larger than this blocks crack transfer, m


def _kind(mat):
    m = MATERIALS.get(mat)
    return m.kind if m else "metal"


def d_eff(ammo):
    d = ammo.d_mm / 1000.0
    return 0.35 * d if ammo.cls == "heat" else d


class DamageField:
    def __init__(self, layers, n=GRID_N, R=GRID_R):
        self.n, self.R = n, R
        self.cell = 2 * R / (n - 1)
        ax = np.linspace(-R, R, n)
        self.X, self.Y = np.meshgrid(ax, ax, indexing="xy")   # X[j,i] — x, Y[j,i] — y
        self.layers = [SV.Layer(**{**l.__dict__}) for l in layers]
        self.G = [np.full((n, n), float(l.dmg)) for l in layers]
        self.dth = [float(l.dth) for l in layers]
        self.T = [np.zeros((n, n)) for _ in layers]   # accumulated D that arrived only through crack transfer

    def local(self, i, x, y, rf):
        """Mean D of layer i within a circle of radius rf around the point (x, y)."""
        rf = max(rf, 1.5 * self.cell)
        msk = (self.X - x) ** 2 + (self.Y - y) ** 2 <= rf * rf
        return float(self.G[i][msk].mean()) if msk.any() else 0.0

    def apply_shock(self, cond, temp):
        t_pre = cond.get("t_pre")
        if t_pre is None:
            return
        for i, l in enumerate(self.layers):
            if l.mat == ERA_KEY or l.mat not in MATERIALS:
                continue
            dth, _ = SV.thermal_shock_damage(MATERIALS[l.mat], float(t_pre), temp, float(cond.get("alpha_f", 1.0)))
            if dth > 0:
                self.G[i] = 1.0 - (1.0 - self.G[i]) * (1.0 - dth)
                self.dth[i] = 1.0 - (1.0 - self.dth[i]) * (1.0 - dth)

    def deposit(self, i, x, y, dn, rd):
        if dn <= 0:
            return None
        g = np.exp(-(((self.X - x) ** 2 + (self.Y - y) ** 2) / (rd * rd)))
        new = 1.0 - (1.0 - self.G[i]) * (1.0 - np.clip(dn * g, 0, 1))
        delta = new - self.G[i]
        self.G[i] = new
        return delta

    def transfer(self, i, delta, k_crack):
        """Cracks from layer i into its neighbours (by source fraction and receiver susceptibility; an air gap blocks them)."""
        if delta is None or k_crack <= 0:
            return
        src = CRACK_SRC.get(_kind(self.layers[i].mat), 0.0)
        for j, gap in ((i + 1, self.layers[i].gap), (i - 1, self.layers[i - 1].gap if i > 0 else 1.0)):
            if j < 0 or j >= len(self.layers) or gap > GAP_BLOCK or self.layers[j].mat == ERA_KEY:
                continue
            x = k_crack * src * CRACK_TGT.get(_kind(self.layers[j].mat), 0.5) * delta
            new = 1.0 - (1.0 - self.G[j]) * (1.0 - np.clip(x, 0, 1))
            self.T[j] = 1.0 - (1.0 - self.T[j]) * (1.0 - np.clip(x, 0, 1))
            self.G[j] = new


class SeriesResult:
    pass


def run_series(ammo_key, v0, layers, n_hits=10, sigma=0.0, cond=None, mode="NORMAL", yaw=0.0, standoff=0.5,
               witness=True, witness_gap=0.05, k_crack=1.0, seed=7, aim=(0.0, 0.0), ammo_seq=None, positions=None):
    """Series of n_hits hits with Gaussian dispersion sigma (m) around the aim point.
    ammo_seq is an optional list of ammunition keys (otherwise all use ammo_key). Returns SeriesResult."""
    cond = dict(cond or {})
    temp = float(cond.get("temp", 20.0))
    rng = np.random.default_rng(seed)
    field = DamageField(layers)
    field.apply_shock(cond, temp)
    cond_shot = {k: v for k, v in cond.items() if k != "t_pre"}   # the shock is already applied to the grid
    seq = list(ammo_seq) if ammo_seq else [ammo_key] * int(n_hits)
    hits = []
    first_perf = None
    for h, key in enumerate(seq):
        a = AMMO[key]
        v = a.v if (ammo_seq and key != ammo_key) else v0
        sx, sy = (rng.normal(0, sigma), rng.normal(0, sigma)) if sigma > 0 else (0.0, 0.0)
        if positions is not None and h < len(positions):      # given hit points (x, y), m
            sx, sy = positions[h][0] - aim[0], positions[h][1] - aim[1]
        x = float(np.clip(aim[0] + sx, -GRID_R, GRID_R))
        y = float(np.clip(aim[1] + sy, -GRID_R, GRID_R))
        de = d_eff(a)
        L = []
        dloc = []
        for i, l in enumerate(field.layers):
            nl = SV.Layer(**{**l.__dict__})
            d0 = field.local(i, x, y, de) if l.mat != ERA_KEY else float(field.local(i, x, y, 0.0) >= 0.99)
            nl.dmg = d0
            nl.dth = field.dth[i]
            # hit position relative to the plate: stretched by 1/cos along the slope
            ca = max(math.cos(math.radians(min(l.angle, 80))), 0.2)
            if l.w > 0 or l.h > 0:            # auto-sized plates are treated as extended (they cover the field); only user-sized ones are offset
                nl.ou = l.ou + y / ca
                nl.ov = l.ov + x
            L.append(nl)
            dloc.append(d0)
        so = standoff if a.cls == "heat" else standoff
        res = SV.solve(key, v, L, mode, yaw, so, witness, witness_gap, cond_shot)
        depth = sum(s.depth for s in res.slabs if s.role != "witness")
        perf = res.verdict == 'PENETRATED'
        miss = perf and depth <= 1e-6      # the projectile missed all plates (the dispersion went outside the plate size)
        if miss:
            perf = False
        deltas = []
        for i, l in enumerate(field.layers):
            dr = float(res.damage[i]) if i < len(res.damage) else dloc[i]
            dn = (dr - dloc[i]) / max(1.0 - dloc[i], 1e-6) if dloc[i] < 0.999 else 0.0
            dn = max(0.0, min(dn, 1.0))
            if l.mat == ERA_KEY:                      # flat disc of the tile radius; cracks are not transferred from ERA to neighbours
                if dn > 0.5:
                    msk = (field.X - x) ** 2 + (field.Y - y) ** 2 <= ERA_TILE ** 2
                    field.G[i][msk] = 1.0
                deltas.append(None)
                continue
            rd = max(ZONE.get(_kind(l.mat), 2.5) * de, 1.2 * field.cell)
            deltas.append(field.deposit(i, x, y, dn, rd))
        for i, dl in enumerate(deltas):
            field.transfer(i, dl, k_crack)
        if perf and first_perf is None:
            first_perf = h + 1
        hits.append(dict(n=h + 1, ammo=key, x=x, y=y, verdict='MISS' if miss else res.verdict, depth=depth, perf=perf, miss=miss,
                         d_before=dloc, d_after=[float(g.max()) for g in field.G]))
    out = SeriesResult()
    out.field, out.hits, out.first_perf = field, hits, first_perf
    out.n, out.sigma, out.k_crack, out.cond = len(seq), sigma, k_crack, cond
    out.layers = field.layers
    out.stats = [dict(mat=l.mat.split("~")[0], mean=float(field.G[i].mean()), peak=float(field.G[i].max()),
                      area50=float((field.G[i] > 0.5).mean()), transferred=float(field.T[i].max()))
                 for i, l in enumerate(field.layers)]
    return out


def series_stats(ammo_key, v0, layers, n_hits, sigma, runs=12, **kw):
    """Statistics over several series with different random dispersions: distribution of the first-penetration hit number."""
    firsts, perfs = [], []
    for r in range(runs):
        s = run_series(ammo_key, v0, layers, n_hits, sigma, seed=100 + r, **kw)
        firsts.append(s.first_perf)
        perfs.append(sum(1 for h in s.hits if h["perf"]))
    ok = [f for f in firsts if f]
    return dict(runs=runs, p_perf=len(ok) / runs, first_mean=float(np.mean(ok)) if ok else None,
                first_min=min(ok) if ok else None, first_max=max(ok) if ok else None,
                perfs_mean=float(np.mean(perfs)))


def series_lines(s, st=None):
    L = ['Series: %d hits, dispersion σ=%.0f mm, k_crack=%.2f' % (s.n, 1000 * s.sigma, s.k_crack)]
    if s.first_perf:
        L.append('first penetration: hit #%d' % s.first_perf)
    else:
        L.append('the armor withstood all %d hits' % s.n)
    L.append('penetrations in the series: %d of %d, missed the plate: %d' % (sum(1 for h in s.hits if h["perf"]), s.n, sum(1 for h in s.hits if h["miss"])))
    L.append('layer       mean D   peak D  S(D>0.5)  peak from cracks')
    for i, r in enumerate(s.stats):
        L.append("%d %-8s %6.2f  %5.2f  %6.0f%%   +%.2f" % (i + 1, r["mat"][:8], r["mean"], r["peak"], 100 * r["area50"], r["transferred"]))
    if st:
        L.append('over %d series: P(penetration) %.0f%%%s' % (
            st["runs"], 100 * st["p_perf"],
            ', first #%.1f (%d–%d)' % (st["first_mean"], st["first_min"], st["first_max"]) if st["first_mean"] else ""))
    return L


def export_series(folder, s):
    os.makedirs(folder, exist_ok=True)
    files = []
    p = os.path.join(folder, "series_hits.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["n", "ammo", "x_mm", "y_mm", "verdict", "path_mm"] + ["D%d_after" % (i + 1) for i in range(len(s.layers))])
        for h in s.hits:
            w.writerow([h["n"], h["ammo"], round(1000 * h["x"], 1), round(1000 * h["y"], 1), h["verdict"], round(1000 * h["depth"]),
                        *[round(d, 3) for d in h["d_after"]]])
    files.append(p)
    for i, g in enumerate(s.field.G):
        p = os.path.join(folder, "damage_grid_layer%d_%s.csv" % (i + 1, s.layers[i].mat.split("~")[0]))
        np.savetxt(p, g, delimiter=";", fmt="%.3f")
        files.append(p)
    return files
