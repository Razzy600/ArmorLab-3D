"""Hypervelocity impact (v > 3 km/s): simplified estimate for compact projectiles (micrometeoroids).
Reference relations: Cour-Palais (NASA) for penetration into a thick target, shock Hugoniots Us=c0+s*up for the
vaporized fraction, and the debris-cloud expansion cone (Whipple shield). The cloud parameters (CONE_DEG, SPREAD_EXP, PERF_K_CLOUD, VAP_K) are fitted to the NASA
Whipple-shield reference equation (Christiansen, ble_whipple) for Al on Al, v=7–15 km/s, normal impact: critical-diameter
error ~7 % on the fit and ~10 % off it. Other materials are extrapolation; vaporization thresholds are assumptions."""
import math

HV_V = 3000.0            # regime threshold, m/s
PERF_K = 1.8             # plate is perforated when T <= PERF_K * P (Cour-Palais, spall thickness)
CONE_DEG = 40.0          # half-angle of the debris cloud cone; calibrated to the Whipple BLE (literature: 30–45°)
SPREAD_EXP = 0.25       # P_cloud = P_compact * s^(-SPREAD_EXP), s = cloud area / projectile area (calibrated to the BLE)
PERF_K_CLOUD = 1.8       # same for debris-cloud impact (the standard 1.8 fitted the BLE)
EJ_T = 2.0               # limit of the ejected slug thickness, in projectile diameters (assumption; does not affect the BLE calibration)
VAP_K = 0.0             # cloud mass reduction due to vaporization: the BLE calibration gave 0 (vaporization is kept as a diagnostic)
EV0, EV1 = 5.0e6, 1.5e7  # J/kg: onset and full vaporization (Al-like projectile), assumption
HUG_P = (5350.0, 1.34)   # Al: c0, s
HUG_T = (4570.0, 1.49)   # target (steel-like), assumption


def cp_depth(d, rho_p, rho_t, hb, c_kms, v, theta_deg=0.0):
    """Penetration depth into a thick target, m (Cour-Palais); d in m, v in m/s, hb = Brinell hardness."""
    dcm = d * 100.0
    P = 5.24 * dcm ** (19.0 / 18.0) * hb ** -0.25 * math.sqrt(rho_p / rho_t) * (v / 1000.0 * math.cos(math.radians(theta_deg)) / c_kms) ** (2.0 / 3.0)
    return P / 100.0


def vapor_fraction(rho_p, rho_t, v):
    """Fraction of projectile material vaporized by the shock wave (impedance matching on the Hugoniots)."""
    cp, sp = HUG_P
    ct, st = HUG_T
    lo, hi = 0.0, v
    for _ in range(60):
        up = 0.5 * (lo + hi)
        pp = rho_p * (cp + sp * up) * up
        ut = v - up
        pt = rho_t * (ct + st * ut) * ut
        if pp > pt:
            hi = up
        else:
            lo = up
    e = 0.5 * up * up
    return max(0.0, min(1.0, (e - EV0) / (EV1 - EV0))), up, rho_p * (cp + sp * up) * up


def hb_of(mat):
    return max(mat.yield_gpa * 1000.0 / 3.0, 60.0) if mat.yield_gpa > 0 else 100.0


def c_of(mat):
    return math.sqrt(mat.e_gpa * 1e9 / mat.rho) / 1000.0 if mat.e_gpa > 0 else 4.5


def run(ammo, rho_p, v0, plates, materials, theta=0.0):
    """plates: [(mat_key, T_los_m, gap_after_m, kind)]. Returns the per-layer event list and the result."""
    d = ammo.d_mm / 1000.0
    L = getattr(ammo, "L_mm", 0.0) / 1000.0
    if L > 0:       # cylinder d×L (micrometeoroids in data.py): mass from the cylinder, diameter of the equal-mass sphere
        m = rho_p * math.pi * d * d * L / 4.0
        d = (6.0 * m / (math.pi * rho_p)) ** (1.0 / 3.0)
    else:
        m = rho_p * math.pi * d ** 3 / 6.0
    v = v0
    out = []
    spread_s = 1.0
    cloud = False
    d_eq = d
    for key, T, gap, kind in plates:
        mat = materials[key]
        if kind == "elastomer" or mat.kind == "composite" and mat.rho < 500:
            # light layer: does not break up the cloud, only slows it slightly (assumption)
            out.append(dict(mat=key, depth=0.0, perf=True, v_in=v, v_out=v, note='light layer, lets the cloud through'))
            continue
        P = cp_depth(d_eq, rho_p, mat.rho, hb_of(mat), c_of(mat), v, theta)
        P /= spread_s ** SPREAD_EXP
        fv, up, pshock = vapor_fraction(rho_p, mat.rho, v)
        if T > (PERF_K_CLOUD if cloud else PERF_K) * P:
            depth = min(P, T)
            out.append(dict(mat=key, depth=depth, perf=False, v_in=v, v_out=0.0, fv=fv, p_gpa=pshock / 1e9,
                            note='stopped, P=%.1f mm (Cour-Palais), vaporized %.0f%%, shock pressure %.0f GPa' % (1000 * depth, 100 * fv, pshock / 1e9)))
            return out, False
        # penetration: debris cloud
        m_ej = mat.rho * math.pi * (d_eq / 2) ** 2 * min(T, EJ_T * d_eq)   # a thick plate ejects a crater spray, not a whole plug
        m_c = (m + 0.5 * m_ej) * (1.0 - VAP_K * fv)          # the vaporized fraction hardly penetrates the next layer (assumption)
        v_c = v * m / (m + 0.5 * m_ej)
        v_c = max(v_c, 0.3 * v)
        R = d / 2 + max(gap, 0.0) * math.tan(math.radians(CONE_DEG)) + 0.3 * T
        d_eq = (6.0 * max(m_c, 1e-9) / (math.pi * rho_p)) ** (1.0 / 3.0)
        spread_s = max(1.0, R * R / (d_eq / 2) ** 2)
        cloud = True
        out.append(dict(mat=key, depth=T, perf=True, v_in=v, v_out=v_c, fv=fv, p_gpa=pshock / 1e9,
                        note='perforated; cloud %.1f g, v=%.0f m/s, radius %.0f mm after the %.0f mm gap, vaporized %.0f%%' % (
                            1000 * m_c, v_c, 1000 * R, 1000 * gap, 100 * fv)))
        m, v = m_c, v_c
        if m_c < 1e-6:
            return out, False
    return out, True


# --------------------------------------------------------------------------------------------
# Reference ballistic-limit equation for the Whipple shield (Christiansen, NASA JSC, ISS-class)
# --------------------------------------------------------------------------------------------
def ble_whipple(v_kms, t_b_cm, S_cm, t_w_cm, rho_p=2.7, rho_b=2.7, sigma_ksi=36.0, theta_deg=0.0):
    """Critical sphere diameter (cm): larger means the rear wall is perforated. Units: cm, g/cm3, ksi, km/s.
    Formulas after Christiansen 1993 (NASA JSC reviews); the "tent" interpolation is linear in V."""
    th = math.radians(theta_deg)
    c = math.cos(th)
    v_lv = 3.0 / c ** 0.5
    v_hv = 7.0 / c ** 0.5 if theta_deg < 65 else 7.0 / c ** 0.5

    def d_lv(v):
        return ((t_w_cm * (sigma_ksi / 40.0) ** 0.5 + t_b_cm) / (0.6 * c ** (5.0 / 3.0) * rho_p ** 0.5 * v ** (2.0 / 3.0))) ** (18.0 / 19.0)

    def d_hv(v):
        return 3.918 * t_w_cm ** (2.0 / 3.0) * S_cm ** (1.0 / 3.0) * rho_p ** (-1.0 / 3.0) * rho_b ** (-1.0 / 9.0) * (v * c) ** (-2.0 / 3.0) * (sigma_ksi / 70.0) ** (1.0 / 3.0)

    if v_kms <= v_lv:
        return d_lv(v_kms)
    if v_kms >= v_hv:
        return d_hv(v_kms)
    a, b = d_lv(v_lv), d_hv(v_hv)
    return a + (b - a) * (v_kms - v_lv) / (v_hv - v_lv)
