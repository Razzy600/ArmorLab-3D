"""Statistics (Monte Carlo, V50), chart data and result export."""
import csv
import json
import math
import time

import numpy as np

from .data import AMMO, MATERIALS, ERA_KEY
from . import solver as SV


def _wilson(k, n, z=1.96):
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - h) / d), min(1.0, (c + h) / d)


class MonteCarlo:
    """Step-wise Monte Carlo: material density ±s_rho, strength ±s_str (normal, truncated at 3 sigma).
    For kinetic threats - a velocity grid, V50 (50% penetration velocity) and V05 (holds with 95% probability)."""

    def __init__(self, ammo_key, v0, layers, n=60, s_rho=0.05, s_str=0.10, yaw=0.0, standoff=0.0,
                 witness=True, witness_gap=0.05, cond=None, seed=7):
        self.ammo_key, self.v0 = ammo_key, v0
        self.layers = [SV.Layer(**{**l.__dict__}) for l in layers]
        self.n, self.s_rho, self.s_str = n, s_rho, s_str
        self.yaw, self.standoff, self.witness, self.wg, self.cond = yaw, standoff, witness, witness_gap, cond
        self.rng = np.random.default_rng(seed)
        a = AMMO[ammo_key]
        self.heat = a.cls == "heat"
        self.speeds = [v0] if self.heat else [v0 * f for f in np.linspace(0.55, 1.25, 11)]
        self.jobs = [(vi, k) for vi in range(len(self.speeds)) for k in range(n)]
        self.pos = 0
        self.hits = [0] * len(self.speeds)
        self.cnt = [0] * len(self.speeds)
        self.wit = []          # witness depth at v0 (m)
        self._keys0 = set(MATERIALS.keys())
        self.done = False
        self.result = None

    @property
    def progress(self):
        return self.pos / max(len(self.jobs), 1)

    def _perturbed(self):
        lay = []
        for l in self.layers:
            nl = SV.Layer(**{**l.__dict__})
            if l.mat != ERA_KEY and l.mat in MATERIALS:
                fr = float(np.clip(self.rng.normal(0, self.s_rho), -3 * self.s_rho, 3 * self.s_rho))
                fs = float(np.clip(self.rng.normal(0, self.s_str), -3 * self.s_str, 3 * self.s_str))
                nl.mat = SV.material_variant(l.mat, 1 + fr, 1 + fs, 1.0)
            lay.append(nl)
        return lay

    def step(self, k=8):
        for _ in range(k):
            if self.pos >= len(self.jobs):
                break
            vi, _k = self.jobs[self.pos]
            self.pos += 1
            lay = self._perturbed()
            cnd = self.cond
            if cnd and cnd.get("t_pre") is not None:   # spread of Δα (thermal-expansion mismatch of the phases) ±20 %
                cnd = dict(cnd, alpha_f=float(np.clip(self.rng.normal(1.0, 0.2), 0.4, 1.6)))
            r = SV.solve(self.ammo_key, self.speeds[vi], lay, "NORMAL", self.yaw, self.standoff,
                         self.witness, self.wg, cnd)
            self.cnt[vi] += 1
            if r.verdict == 'PENETRATED':
                self.hits[vi] += 1
            if abs(self.speeds[vi] - self.v0) < 1e-6:
                self.wit.append(r.witness_depth if r.verdict == 'PENETRATED' else 0.0)
        if self.pos >= len(self.jobs):
            self._finish()

    def _finish(self):
        for k in [k for k in MATERIALS if k not in self._keys0]:
            del MATERIALS[k]
        P = [h / c if c else 0.0 for h, c in zip(self.hits, self.cnt)]
        i0 = int(np.argmin([abs(v - self.v0) for v in self.speeds]))
        lo, hi = _wilson(self.hits[i0], self.cnt[i0])
        res = dict(speeds=list(map(float, self.speeds)), P=P, p_nom=P[i0], ci=(lo, hi), n=self.n,
                   wit_mean=float(np.mean(self.wit)) if self.wit else 0.0,
                   wit_std=float(np.std(self.wit)) if self.wit else 0.0, v50=None, v05=None)
        if not self.heat:
            res["v50"] = _cross(self.speeds, P, 0.5)
            res["v05"] = _cross(self.speeds, P, 0.05)
        self.result = res
        self.done = True

    def lines(self):
        r = self.result
        if not r:
            return ['computing… %.0f%%' % (100 * self.progress)]
        L = ['Monte Carlo: %d runs per point, σρ=%.0f%%, σstrength=%.0f%%' % (r["n"], 100 * self.s_rho, 100 * self.s_str),
             'P(penetration) at the given v: %.0f%%  (95%% CI %.0f–%.0f%%)' % (100 * r["p_nom"], 100 * r["ci"][0], 100 * r["ci"][1])]
        if self.heat:
            L.append('behind the target (witness): %.0f ± %.0f mm' % (1000 * r["wit_mean"], 1000 * r["wit_std"]))
            L.append('V50 is not defined for shaped charges (fixed velocity)')
        else:
            L.append('V50 (50%% penetration): %s' % ('%.0f m/s' % r["v50"] if r["v50"] else 'out of range %.0f–%.0f' % (r["speeds"][0], r["speeds"][-1])))
            L.append('V05 (armor holds with 95%% probability): %s' % ('up to %.0f m/s' % r["v05"] if r["v05"] else 'out of range'))
            L.append("P(v): " + " ".join("%.0f:%d%%" % (v, round(100 * p)) for v, p in zip(r["speeds"][::2], r["P"][::2])))
        return L


def _cross(xs, ps, level):
    for i in range(len(xs) - 1):
        a, b = ps[i], ps[i + 1]
        if (a - level) * (b - level) <= 0 and a != b:
            return xs[i] + (level - a) / (b - a) * (xs[i + 1] - xs[i])
    return None


# ----------------------------------------------------------------------- chart data
def chart_data(res, layers, group_rows, mass_sweep=None):
    """Returns a dict of datasets for the 4 charts."""
    d = {}
    tr = res.track
    s = np.asarray(tr.get("s", [])) * 1000.0
    v = np.asarray(tr.get("v", []))
    d["v_depth"] = (s, v)
    d["energy"] = [(r["name"], r["e"] / 1000.0) for r in group_rows if not r["witness"] and r["mode"] != 'missed plate']
    d["mass_eff"] = mass_sweep or []
    if res.cls == "heat":
        cs = res.jet.get("coh_slab", {})
        pts = []
        for j, c in sorted(cs.items()):
            if j < len(res.slab_defs):
                pts.append((res.slab_defs[j].s_front * 1000.0, c))
        d["aux"] = ("heat", pts)
    else:
        d["aux"] = ("rod", (s, np.asarray(tr.get("L", [])) * 1000.0))
    return d


def mass_sweep(ammo_key, v0, layers, mode, yaw, standoff, witness, wg, cond, factors=None):
    """Curve: layer thickness scale -> mass efficiency (RHA of the same resistance / target mass)."""
    out = []
    for k in (factors or [0.4, 0.55, 0.7, 0.85, 1.0, 1.2, 1.4, 1.7, 2.0]):
        lay = [SV.Layer(**{**l.__dict__}) for l in layers]
        for l in lay:
            l.t = max(0.002, l.t * k)
        r = SV.solve(ammo_key, v0, lay, "NORMAL", yaw, standoff, witness, wg, cond)
        areal = sum(MATERIALS[l.mat].rho * l.t for l in lay if l.mat in MATERIALS)
        if r.verdict == 'PENETRATED':
            rh = r.rhae
        else:
            rh = r.free_depth
        eff = rh * 7850.0 / areal if areal > 0 else 0.0
        out.append((areal, eff, r.verdict == 'PENETRATED'))
    return out


# ----------------------------------------------------------------------- export
def export_all(folder, res, layers, group_rows, report_text, extra=None):
    import os
    os.makedirs(folder, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    f_lay = os.path.join(folder, "layers_%s.csv" % stamp)
    with open(f_lay, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(['layer', 'angle_deg', 'LOS_mm', 'path_mm', 'v_in_m/s', 'v_out_m/s', 'perforated', 'energy_kJ', 'mode',
                    'spall_n', 'spall_v_m/s', 'spall_m_g', 'after_liner_v_m/s', 'damage_after'])
        dm = list(res.damage) if res.damage else []
        for r in group_rows:
            w.writerow([r["name"], "%.1f" % r["angle"], "%.1f" % (r["T"] * 1000), "%.1f" % (r["depth"] * 1000), "%.0f" % r["v_in"],
                        "%.0f" % r["v_out"], int(r["perf"]), "%.1f" % (r["e"] / 1000), r["mode"], r["sp_n"], "%.0f" % r["sp_v"],
                        "%.1f" % (r["sp_m"] * 1000), "" if r["sp_rv"] < 0 else "%.0f" % r["sp_rv"],
                        "" if r["witness"] or r["parent"] >= len(dm) else "%.2f" % dm[r["parent"]]])
    f_tr = os.path.join(folder, "track_%s.csv" % stamp)
    tr = res.track
    with open(f_tr, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(['t_us', 's_mm', 'v_m/s', 'L_mm'])
        n = len(tr.get("t", []))
        for i in range(n):
            w.writerow(["%.2f" % (tr["t"][i] * 1e6), "%.2f" % (tr["s"][i] * 1000), "%.0f" % tr["v"][i],
                        "%.1f" % (tr["L"][i] * 1000) if len(tr.get("L", [])) > i else ""])
    js = dict(ammo=res.ammo, verdict=res.verdict, mode=res.mode, free_depth_mm=res.free_depth * 1000,
              rhae_mm=res.rhae * 1000, witness_depth_mm=res.witness_depth * 1000, cond=res.cond,
              damage_after=[float(x) for x in res.damage],
              layers=[dict(mat=l.mat, t_mm=l.t * 1000, angle=l.angle, gap_mm=l.gap * 1000, dmg=l.dmg) for l in layers],
              jet_energy_balance_J={k: float(v) for k, v in res.jet.get("e_bal", {}).items()} if res.cls == "heat" else None,
              acoustic=[dict(i=i, a=a, b=b, Tp=float(tp)) for i, a, b, tp in res.imp],
              pre=res.pre and dict(name=res.pre["name"], verdict=res.pre["verdict"]), extra=extra, report=report_text)
    f_js = os.path.join(folder, "result_%s.json" % stamp)
    with open(f_js, "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1, default=float)
    return [f_lay, f_tr, f_js]
