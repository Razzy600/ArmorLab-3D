import sys, time
from armorlab.solver import *
from armorlab.solver import _JETCAL
from armorlab.data import *
def run(ak, t_mm, ang, mat="RHA", mode="ADVANCED", v=None):
    a = AMMO[ak]
    lay=[Layer(mat, t_mm/1000, ang, 0)]
    r = solve(ak, v or a.v, lay, mode, witness=False)
    return r
if __name__=="__main__":
    print("== semi-infinite RHA, 0 deg (mm) ==")
    for k,a in AMMO.items():
        if a.cls=="heat":
            lf,tb=_JETCAL[k]
            D=a.d_mm/1000
            print(k, "rated", a.rated_mm, "lf %.2f tb %.0fus"%(lf,tb*1e6), end=" | ")
            for so in (0.5,1,2,4,6,8,10):
                print("S=%.1fCD:%.0f"%(so,1000*free_rha_depth(a,a.v,so*D)), end=" ")
            print()
        else:
            print(k, "L/D=%.0f v=%d"%(a.L_mm/a.d_mm,a.v), "P=%.0f mm"%(1000*free_rha_depth(a,a.v,0)), "mass=%.2fkg"%rod_mass(a))


# --- formulas (calc.py): the integrated Tate result must match the solver
try:
    from armorlab import calc as _C
    from armorlab.data import AMMO as _A, CORES as _CO, MATERIALS as _M
    from armorlab.solver import free_rha_depth as _fr
    for _k in ("M829A1", "DM53", "3BM42"):
        _a = _A[_k]; _c = _CO[_a.core]; _m = _M["RHA"]
        _p = _C.tate_depth(_a.L_mm / 1000, _a.v, _c.rho, _m.rho, _c.yield_gpa * 1e9, _m.rt_gpa * 1e9)[1]
        _s = _fr(_a, _a.v, 0)
        assert abs(_p - _s) < 0.01 * _s + 0.003, (_k, _p, _s)
    for _c in _C.CALCS:
        _out = _C.run(_c.key, {f.key: f.default for f in _c.fields})
        assert _out and not _out[0].startswith('Error'), (_c.key, _out)
    print('calc OK: Tate = solver, all calculators (formulas 1-17) respond')
except Exception as _e:
    print("calc FAIL", _e)

try:
    from armorlab import solver as _S, analysis as _AN
    _L = _S.Layer
    _lay = [_L("SIC", .08, 0, .03), _L("HHS", .25), _L("RHA", .05)]
    # conditions: heat and fatigue do not strengthen the armor; cold does not weaken metal
    _r0 = _S.solve("M829A1", 1575, _lay, "NORMAL", 0, 0, True, .05)
    _r1 = _S.solve("M829A1", 1575, _lay, "NORMAL", 0, 0, True, .05, dict(temp=600, por=.03, cycles=20))
    assert _r1.witness_depth >= _r0.witness_depth - 1e-9, 'conditions'
    # damage accumulates and weakens the armor
    _d = _r0.damage
    _r2 = _S.solve("M829A1", 1575, _S._with_damage(_lay, _d), "NORMAL", 0, 0, True, .05)
    assert _r2.witness_depth >= _r0.witness_depth - 1e-9 and all(b >= a for a, b in zip([l.dmg for l in _lay], _r2.damage)), 'damage'
    # tandem: the precursor exists and triggers the ERA
    _rk = _S.solve("KORNET", 300, [_L("ERA", .03, 0, .1), _L("RHA", .1)], "NORMAL", 0, 6 * .152, True, .05)
    assert _rk.pre and _rk.pre["dmg"][0] >= .99, 'tandem'
    # acoustics and Monte Carlo
    _t20 = _S.interface_report(_lay, 20.0)[0][3] if False else None
    _lr = [_L("HHS", .5), _L("RUBBER", .01), _L("ARAMID", .03)]
    _tp20 = _S.interface_report(_lr, 20.0)[0][3]; _tp50 = _S.interface_report(_lr, -50.0)[0][3]
    assert 0.08 < _tp20 < 0.20 and 0.25 < _tp50 < 0.50 and _tp50 > _tp20 * 2, ('Tp of rubber', _tp20, _tp50)
    _lt = lambda el, T: _S.interface_report([_L("HHS", .5), _L(el, .01), _L("ARAMID", .03)], T)[0][3]
    assert _lt("RUBBER", 300) > _lt("RUBBER", 20) * 2 and abs(_lt("SILICONE", 200) - _lt("SILICONE", 20)) < 1e-3, 'thermal limit'
    assert _S.transmission(1.0, 1.0) == 1.0 and 0 < _S.transmission(1.0, 50.0) < 0.2
    _m = _AN.MonteCarlo("M829A1", 1575, _lay[1:], n=10, witness=False)
    while not _m.done:
        _m.step(30)
    assert _m.result["v50"] is not None, "V50"
    print('new models OK: conditions, damage, tandem, impedance, V50')
except Exception as _e:
    import traceback; traceback.print_exc(); print('new models FAIL', _e)

# thermal + impact synergy: D grows with k; at k=0 it equals independent summation
from armorlab import solver as _S
_L = lambda: [_S.Layer("SIC", 0.08, 60), _S.Layer("HHS", 0.3, 60), _S.Layer("ARAMID", 0.03, 60)]
_c = {"temp": -20.0, "t_pre": 1000.0}
_r0 = _S.solve("TOW2A", 300, _L(), "ULTRA", 0, 0.762, True, 0.05, dict(_c, k_syn=0.0))
_r1 = _S.solve("TOW2A", 300, _L(), "ULTRA", 0, 0.762, True, 0.05, dict(_c, k_syn=0.5))
assert _r1.damage[0] > _r0.damage[0] + 1e-3 and _r1.damage[0] <= 1.0
assert _r0.dth[0] > 0.01
print('thermal + impact synergy OK')

# series: 2D D field, dispersion, crack transfer
from armorlab import series as _SR
_L2 = [_S.Layer("SIC", 0.05, 0), _S.Layer("HHS", 0.1, 0), _S.Layer("ARAMID", 0.03, 0)]
_a = _SR.run_series("BOPS30", 1400, _L2, 6, 0.0, k_crack=0.0)
_b = _SR.run_series("BOPS30", 1400, _L2, 6, 0.0, k_crack=1.0)
assert _b.stats[1]["peak"] > _a.stats[1]["peak"] + 1e-3 and _a.stats[1]["transferred"] < 1e-9   # cracks from ceramic into the neighbouring layer
_c = _SR.run_series("BOPS30", 1400, _L2, 6, 0.08)
assert _c.field.G[0].max() <= 1.0 and len({(h["x"], h["y"]) for h in _c.hits}) > 1                  # dispersion gives different points
assert _c.stats[0]["area50"] >= 0.0
print('series (dispersion, D grid, cracks) OK')

# ERA cuts the jet; damaged ceramic disrupts coherence less
_E = "ERA"
_pk = lambda: [_S.Layer("SIC", 0.05, 60), _S.Layer("HHS", 0.25, 60)]
_a = _S.solve("KORNETM_P", 300, _pk(), "ULTRA", 0, 0.3, True, 0.05)
_b = _S.solve("KORNETM_P", 300, [_S.Layer(_E, 0.03, 60)] + _pk(), "ULTRA", 0, 0.3, True, 0.05)
assert sum(s.depth for s in _b.slabs if s.role == "plate") < sum(s.depth for s in _a.slabs if s.role == "plate")
_ce0 = _S.ceramic_effect(8000, 0.1, 0.152)["coherence"]; _ce1 = _S.ceramic_effect(8000, 0.1, 0.152, dmg=0.5)["coherence"]
assert _ce1 > _ce0
print('ERA (jet cutting) and ceramic D OK')

# defects, self-sharpening, hypervelocity, heat transfer
_T = lambda: [_S.Layer("AL7039", 0.02, 0), _S.Layer("RHA", 0.2, 0)]
_a = _S.solve("M829A1", 1750, [_S.Layer("RHA", 0.8, 0)], "ULTRA", 0, 0.5, False, 0.05, {})
_b = _S.solve("M829A1", 1750, [_S.Layer("RHA", 0.8, 0)], "ULTRA", 0, 0.5, False, 0.05, {"sharp": 0.05})
assert _b.slabs[0].depth > _a.slabs[0].depth
_w = lambda gap: [_S.Layer("RHA", 0.004, 0, gap), _S.Layer("RHA", 0.020, 0)]
_g0 = _S.solve("METEO5", 15000, _w(0.0), "ULTRA", 0, 0.5, False, 0.05, {})
_g1 = _S.solve("METEO5", 15000, _w(0.1), "ULTRA", 0, 0.5, False, 0.05, {})
assert _g0.verdict == 'PENETRATED' and _g1.verdict == 'STOPPED'      # the Whipple gap saves the rear wall
_s0 = _S.solve("TOW2A", 300, [_S.Layer("HHS", 0.42, 60)], "ULTRA", 0, 0.762, False, 0.05, {})
_s1 = _S.solve("TOW2A", 300, [_S.Layer("HHS", 0.42, 60)], "ULTRA", 0, 0.762, False, 0.05, {"surf": 8})
assert _s1.damage[0] > _s0.damage[0]
from armorlab.thermal1d import heat_1d
_t1 = heat_1d([("TI64", .03), ("INSUL", .02), ("AL7039", .02)], 2500, 120)[0]
_t2 = heat_1d([("TI64", .03), ("INSUL", .04), ("AL7039", .02)], 2500, 120)[0]
assert 20 <= _t2 < _t1 < 400
print('defects, self-sharpening, hypervelocity, heat transfer OK')

# hypervelocity calibration to the Whipple-shield reference equation (NASA), Al on Al
import types as _ty, math as _m
from armorlab import hyper as _H
from armorlab.data import MATERIALS as _M
def _dc(v, tb, S, tw):
    lo, hi = 0.05e-3, 60e-3
    for _ in range(36):
        d = _m.sqrt(lo * hi)
        ok = _H.run(_ty.SimpleNamespace(d_mm=d * 1000), 2700.0, v, [("AL5083", tb, S, ""), ("AL5083", tw, 0.0, "")], {"AL5083": _M["AL5083"]})[1]
        lo, hi = (lo, d) if ok else (d, hi)
    return d
for _v in (8, 11, 14):
    _ref = _H.ble_whipple(_v, 0.12, 8.0, 0.4) * 10
    assert abs(_dc(_v * 1000, 0.0012, 0.08, 0.004) * 1000 / _ref - 1) < 0.2, _v
print('hypervelocity: agreement with the Whipple-shield BLE (±20 %) OK')
