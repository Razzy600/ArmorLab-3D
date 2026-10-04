"""1D transient heat conduction through a multilayer wall (implicit scheme, unconditionally stable).
Boundary conditions: the outer surface has a prescribed temperature, the rear is adiabatic. The properties are assumptions."""
import numpy as np

# k W/(m·K), rho kg/m3, c J/(kg·K) — assumptions
PROPS = {"INSUL": (0.08, 250.0, 800.0), "RHA": (45.0, 7850.0, 475.0),
         "SIC": (120.0, 3200.0, 750.0), "RUBBER": (0.2, 1100.0, 1700.0), "ARAMID": (0.04, 1400.0, 1400.0)}
K_KIND = {"metal": 30.0, "ceramic": 25.0, "composite": 0.5, "elastomer": 0.2, "concrete": 1.5}


def props_of(key, materials=None):
    """(k, rho, c): from the PROPS table, otherwise by material kind (assumption)."""
    base = key.split("~")[0]
    if base in PROPS:
        return PROPS[base]
    m = (materials or {}).get(key) or (materials or {}).get(base)
    if m is None:
        return (30.0, 7800.0, 500.0)
    return (K_KIND.get(m.kind, 10.0), m.rho, m.c_jkgk if m.c_jkgk > 0 else 600.0)


def heat_1d(layers, t_out, seconds, t0=20.0, dx=0.5e-3, dt=0.05, props=None):
    """layers: [(key, thickness m)]. Returns (T_rear, T profile, x axis in mm)."""
    pr = dict(PROPS, **(props or {}))
    pr = {k: v for k, v in pr.items()}
    k, rc = [], []
    for key, t in layers:
        n = max(1, int(round(t / dx)))
        kk, rho, c = pr[key] if key in pr else props_of(key)
        k += [kk] * n
        rc += [rho * c] * n
    k, rc = np.array(k), np.array(rc)
    n = len(k)
    kf = 2 * k[:-1] * k[1:] / (k[:-1] + k[1:])      # conductance between cells
    A = np.zeros((n, n))
    for i in range(n):
        A[i, i] = rc[i] / dt
        if i > 0:
            A[i, i] += kf[i - 1] / dx ** 2; A[i, i - 1] = -kf[i - 1] / dx ** 2
        if i < n - 1:
            A[i, i] += kf[i] / dx ** 2; A[i, i + 1] = -kf[i] / dx ** 2
    A[0, :] = 0; A[0, 0] = 1.0
    T = np.full(n, float(t0)); T[0] = t_out
    Ainv = np.linalg.inv(A)
    for _ in range(int(round(seconds / dt))):
        b = rc / dt * T; b[0] = t_out
        T = Ainv @ b
    return float(T[-1]), T, np.arange(n) * dx * 1000


def layer_temps(layers, t_out, seconds, t0=20.0, materials=None, dx=1.0e-3, dt=0.1):
    """layers: [(key, thickness m)] in order from the outer surface. Returns (T_rear, [mean T of each layer])."""
    props = {k: props_of(k, materials) for k, _ in layers}
    Tb, T, x = heat_1d(layers, t_out, seconds, t0, dx=dx, dt=dt, props=props)
    out, i = [], 0
    for k, t in layers:
        n = max(1, int(round(t / dx)))
        out.append(float(np.mean(T[i:i + n])))
        i += n
    return Tb, out
