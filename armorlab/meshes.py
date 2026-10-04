"""Procedural meshes: plate with a (deformable) crater, cylinders, particles."""
from __future__ import annotations
import math
import numpy as np
from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat,
                          GeomVertexArrayFormat, GeomVertexFormat, InternalName, NodePath,
                          GeomPoints, GeomLines, Vec3)

RAD = math.pi / 180.0


def _fmt():
    arr = GeomVertexArrayFormat()
    arr.add_column(InternalName.get_vertex(), 3, Geom.NT_float32, Geom.C_point)
    arr.add_column(InternalName.get_normal(), 3, Geom.NT_float32, Geom.C_normal)
    arr.add_column(InternalName.get_color(), 4, Geom.NT_float32, Geom.C_color)
    f = GeomVertexFormat()
    f.add_array(arr)
    return GeomVertexFormat.register_format(f)


_FMT = None


def vformat():
    global _FMT
    if _FMT is None:
        _FMT = _fmt()
    return _FMT


def smooth(x0, x1, x):
    t = np.clip((x - x0) / max(x1 - x0, 1e-9), 0, 1)
    return t * t * (3 - 2 * t)


def _grid_indices(ni, nj, offset, flip=False):
    """Triangles for an ni x nj grid (vertices row by row: i*nj + j)."""
    ii, jj = np.meshgrid(np.arange(ni - 1), np.arange(nj - 1), indexing="ij")
    a = (ii * nj + jj).ravel() + offset
    b = ((ii + 1) * nj + jj).ravel() + offset
    c = ((ii + 1) * nj + jj + 1).ravel() + offset
    d = (ii * nj + jj + 1).ravel() + offset
    if flip:
        tri = np.stack([a, c, b, a, d, c], axis=1)
    else:
        tri = np.stack([a, b, c, a, c, d], axis=1)
    return tri.reshape(-1, 3)


def _normals(P, ref, flip_by_mean=True):
    """P: (ni,nj,3). ref: (ni,nj,3) outward direction. Returns (ni,nj,3)."""
    di = np.gradient(P, axis=0)
    dj = np.gradient(P, axis=1)
    n = np.cross(di, dj)
    ln = np.linalg.norm(n, axis=2, keepdims=True)
    bad = ln < 1e-14
    n = n / np.where(bad, 1.0, ln)
    sign = np.sign(np.sum(np.sum(n * ref, axis=2)))
    if sign == 0:
        sign = 1.0
    n = n * sign
    n = np.where(bad, ref / (np.linalg.norm(ref, axis=2, keepdims=True) + 1e-12), n)
    return n


def _tri_orient(P, N, ni, nj):
    """Decide whether the indices need flipping: compare the face normal with N."""
    p0 = P[0:-1, 0:-1].reshape(-1, 3)
    p1 = P[1:, 0:-1].reshape(-1, 3)
    p2 = P[1:, 1:].reshape(-1, 3)
    n = np.cross(p1 - p0, p2 - p0)
    nn = N[0:-1, 0:-1].reshape(-1, 3)
    return np.sum(np.sum(n * nn, axis=1)) < 0


class PlateMesh:
    """Plate in local coordinates: u,v in the plane, w outward.
    Front face w=0, rear face w=-t. The origin is the impact point.
    geom: dict(shape='rect', ul, ur, vd, vu) or dict(shape='round', R, ou, ov)."""

    def __init__(self, t, theta_deg, geom, color, section=False, seed=1,
                 nth=72, ns=18, nk=34, name="plate"):
        self.t = t
        self.theta = theta_deg * RAD
        self.tan = math.tan(self.theta)
        self.cos = max(math.cos(self.theta), 0.15)
        self.geom = geom
        self.color = np.array(color + (1.0,), dtype=np.float32)
        self.section = section
        self.rng = np.random.default_rng(seed)
        self.nth, self.ns, self.nk = nth, ns, nk
        base = np.linspace(0, np.pi, nth // 2 + 1) if section else np.linspace(0, 2 * np.pi, nth + 1)
        if geom["shape"] == "rect":
            ul, ur, vd, vu = geom["ul"], geom["ur"], geom["vd"], geom["vu"]
            corners = [math.atan2(vu, ur), math.pi - math.atan2(vu, ul),
                       math.pi + math.atan2(vd, ul), 2 * math.pi - math.atan2(vd, ur)]
            lim = math.pi if section else 2 * math.pi
            extra = [c for c in corners if c <= lim + 1e-9]
            base = np.sort(np.concatenate([base, extra, [c + 1e-4 for c in extra]]))
            base = np.clip(base, 0, lim)
        self.phi = base
        self.g = (np.arange(ns + 1) / ns) ** 1.7
        self.kk = np.linspace(0, 1, nk)
        ph = self.phi
        self.jit_s = (0.5 * np.sin(3 * ph + self.rng.uniform(0, 6)) + 0.35 * np.sin(7 * ph + self.rng.uniform(0, 6))
                      + 0.25 * np.sin(13 * ph + self.rng.uniform(0, 6)))
        self.noise = self.rng.uniform(0.93, 1.07, 4096).astype(np.float32)
        self.bd = self._bdist(self.phi)
        P = len(self.phi)
        self.shapes = {"F": (P, ns + 1), "B": (P, ns + 1), "H": (P, nk),
                       "CR": (nk, ns + 1), "CL": (nk, ns + 1), "S": (P, 2)}
        order = ["F", "B", "H", "S"] + (["CR", "CL"] if section else [])
        self.order = order
        off = 0
        self.offsets = {}
        for k in order:
            self.offsets[k] = off
            off += self.shapes[k][0] * self.shapes[k][1]
        self.nvert = off
        self.vdata = GeomVertexData(name, vformat(), Geom.UH_dynamic)
        self.vdata.set_num_rows(self.nvert)
        self.prim = GeomTriangles(Geom.UH_static)
        self.geom_obj = Geom(self.vdata)
        self.node = GeomNode(name)
        self.np = NodePath(self.node)
        self._flip = {}
        self.buf = np.zeros((self.nvert, 10), dtype=np.float32)
        self._built = False

    # ------------------------------------------------------------------
    def _bdist(self, phi):
        """Distance from the impact point to the plate edge in direction phi."""
        g = self.geom
        c, s = np.cos(phi), np.sin(phi)
        if g["shape"] == "round":
            ou, ov, R = g["ou"], g["ov"], g["R"]
            dc = c * ou + s * ov
            return dc + np.sqrt(np.maximum(dc * dc - (ou * ou + ov * ov) + R * R, 1e-9))
        with np.errstate(divide="ignore", invalid="ignore"):
            tx = np.where(c > 1e-9, g["ur"] / c, np.where(c < -1e-9, g["ul"] / (-c), np.inf))
            ty = np.where(s > 1e-9, g["vu"] / s, np.where(s < -1e-9, g["vd"] / (-s), np.inf))
        return np.minimum(tx, ty)

    def _radius(self, hole, kcur, k, phi, ultra):
        """Hole ring radius r(k, phi): shape (len(k), len(phi))."""
        K = np.asarray(k)[:, None]
        if hole is None or kcur <= 1e-5:
            return np.zeros((len(k), len(phi)))
        kt = np.asarray(hole.k)
        rt = np.asarray(hole.r)
        kmax_h = kt[-1]
        base = np.interp(K, kt, rt)
        # share of the profile reached "now"
        kc = kcur * kmax_h
        # rounding of the crater front
        r_here = np.interp(kc, kt, rt) if hole.perforated is False or kcur < 1 else rt[-1]
        T = self.t / self.cos
        dk = min(max(r_here * 1.1, 1e-4) / T, kc)
        closing = np.where(K <= kc - dk, 1.0,
                           np.sqrt(np.clip(1 - ((K - (kc - dk)) / max(dk, 1e-9)) ** 2, 0, 1)))
        if kcur >= 0.9999 and hole.perforated:
            closing = np.ones_like(closing)
        r = np.where(K <= kc + 1e-9, base * closing, 0.0)
        r = np.minimum(r, 0.8 * self.bd[None, :])
        if hole.k[-1] < 0.999 and kcur >= 0.9999:
            pass
        # roughness
        jit = 1.0 + (0.035 + (0.12 if hole.cone else 0.0)) * self.jit_s[None, :] * (1 + 0.5 * K)
        r = r * jit
        if hole.petals:
            amp = smooth(0.7, 1.0, K) * (0.5 + 0.5 * np.cos(hole.petals * phi[None, :])) ** 2
            r = r * (1 + 1.2 * amp)
        return r

    def _dz_front(self, rho, r_eff, hole, prog):
        q = (rho - r_eff) / np.maximum(r_eff, 2e-3)
        z = hole.lip * np.exp(-q * q) - hole.dish * np.exp(-((q - 2.5) / 2.0) ** 2)
        return z * smooth(0.0, 0.12, prog)

    def _dz_back(self, rho, r_eff, phi, hole, prog):
        z = -hole.bulge * np.exp(-(rho / max(hole.bulge_r, 1e-4)) ** 2) * smooth(0.55, 1.0, prog)
        if hole.petals and hole.perforated:
            qb = np.clip((rho - r_eff) / max(hole.petal_len, 1e-4), 0, 1)
            mod = 0.55 + 0.45 * np.cos(hole.petals * phi)
            z = z - 0.7 * hole.petal_len * (1 - qb) ** 1.5 * mod * smooth(0.8, 1.0, prog)
        if hole.delam and hole.perforated:
            z = z - 0.5 * hole.bulge * np.exp(-(rho / max(hole.bulge_r, 1e-4)) ** 2)
        return z

    # ------------------------------------------------------------------
    def update(self, hole, progress=1.0, ultra=True, heat=0.0):
        """hole - Hole or None (intact plate); progress 0..1 - share of the penetration."""
        t, tan, cos = self.t, self.tan, self.cos
        phi = self.phi
        ns, nk = self.ns, self.nk
        cp, sp = np.cos(phi), np.sin(phi)
        kcur = float(progress)
        has = hole is not None and kcur > 1e-4
        if hole is None:
            from .solver import Hole
            hole = Hole(k=np.array([0.0, 1.0]), r=np.array([0.0, 0.0]))
        prog = kcur
        # 1) hole rings at levels k (for the wall)
        kgrid = self.kk
        R = self._radius(hole if has else None, kcur, kgrid, phi, ultra)   # (nk, P)
        Cx = kgrid * t * tan
        ring_u = Cx[:, None] + R * cp[None, :] / cos
        ring_v = R * sp[None, :]
        # 2) front face
        r0 = R[0]
        Pin_u = ring_u[0]
        Pin_v = ring_v[0]
        rmax = self.bd
        Pout_u = rmax * cp
        Pout_v = rmax * sp
        g = self.g[None, :]
        Fu = Pin_u[:, None] + (Pout_u - Pin_u)[:, None] * g
        Fv = Pin_v[:, None] + (Pout_v - Pin_v)[:, None] * g
        rho_f = np.hypot(Fu, Fv)
        r_eff0 = np.hypot(Pin_u, Pin_v)[:, None]
        Fw = self._dz_front(rho_f, r_eff0, hole, prog) if has else np.zeros_like(Fu)
        F = np.stack([Fu, Fv, Fw], axis=2)
        # 3) rear face
        Cb = t * tan
        r1 = R[-1]
        Bin_u = ring_u[-1]
        Bin_v = ring_v[-1]
        Bout_u = rmax * cp
        Bout_v = rmax * sp
        Bu = Bin_u[:, None] + (Bout_u - Bin_u)[:, None] * g
        Bv = Bin_v[:, None] + (Bout_v - Bin_v)[:, None] * g
        rho_b = np.hypot(Bu - Cb, Bv)
        r_effb = np.hypot(Bin_u - Cb, Bin_v)[:, None]
        Bw = (-t + self._dz_back(rho_b, r_effb, phi[:, None], hole, prog)) if has else np.full_like(Bu, -t)
        Bq = np.stack([Bu, Bv, Bw], axis=2)
        # 4) hole wall
        Hu = ring_u.T
        Hv = ring_v.T
        rho_h = np.hypot(Hu - Cx[None, :], Hv)
        k2 = kgrid[None, :]
        if has:
            fz = self._dz_front(R[0][:, None] * 1.0, R[0][:, None], hole, prog)
            bz = self._dz_back(rho_h, R[-1][:, None], phi[:, None], hole, prog)
            Hw = -k2 * t + (1 - k2) * fz + k2 * bz
        else:
            Hw = -k2 * t * np.ones_like(Hu)
        H = np.stack([Hu, Hv, Hw], axis=2)
        Su = self.bd * cp
        Sv = self.bd * sp
        S = np.stack([np.stack([Su, Sv, np.zeros_like(Su)], axis=1), np.stack([Su, Sv, np.full_like(Su, -t)], axis=1)], axis=1)
        faces = {"F": F, "B": Bq, "H": H, "S": S}
        refs = {"F": np.broadcast_to([0, 0, 1.0], F.shape),
                "B": np.broadcast_to([0, 0, -1.0], Bq.shape)}
        axis = np.stack([Cx[None, :] - Hu, -Hv, np.zeros_like(Hu)], axis=2)
        refs["H"] = axis
        refs["S"] = np.stack([np.stack([cp, sp, np.zeros_like(cp)], axis=1)] * 2, axis=1)
        # 5) cut-away
        if self.section:
            for key, sgn, ph_i in (("CR", 1.0, 0), ("CL", -1.0, -1)):
                rr = R[:, ph_i] / cos
                uin = Cx + sgn * rr
                uout = np.full_like(uin, self.bd[ph_i] * sgn)
                u = uin[:, None] + (uout - uin)[:, None] * g
                kk_ = kgrid[:, None] * np.ones_like(u)
                rf = np.hypot(u, 0.0)
                rb_ = np.abs(u - Cb)
                reff0 = abs(R[0, ph_i] / cos)
                reffb = abs(R[-1, ph_i] / cos)
                if has:
                    dzf = self._dz_front(rf, reff0, hole, prog)
                    dzb = self._dz_back(rb_, reffb, np.full_like(u, 0.0 if sgn > 0 else np.pi), hole, prog)
                    w = -kk_ * t + (1 - kk_) * dzf + kk_ * dzb
                else:
                    w = -kk_ * t
                faces[key] = np.stack([u, np.zeros_like(u), w], axis=2)
                refs[key] = np.broadcast_to([0, -1.0, 0], faces[key].shape)
        # --- buffer assembly ---
        buf = self.buf
        base = self.color
        shade_noise = self.noise
        for key in self.order:
            Pm = faces[key]
            ni, nj = Pm.shape[:2]
            N = _normals(Pm, np.asarray(refs[key], dtype=float))
            off = self.offsets[key]
            n = ni * nj
            pos = Pm.reshape(-1, 3)
            nor = N.reshape(-1, 3)
            col = np.tile(base, (n, 1))
            idx = (np.arange(n) * 7) % 4096
            col[:, :3] *= shade_noise[idx][:, None]
            # darkening near the hole
            if key in ("F", "B"):
                jj = np.tile(np.arange(nj), ni)
                dark = np.exp(-jj / 2.2)[:, None] * 0.45
                col[:, :3] *= (1 - dark)
                if heat > 0:
                    col[:, :3] += np.array([0.55, 0.22, 0.05]) * np.exp(-jj / 2.2)[:, None] * heat
            elif key == "H":
                col[:, :3] *= 0.55
                if heat > 0:
                    col[:, :3] += np.array([0.7, 0.28, 0.06]) * heat
            elif key == "S":
                col[:, :3] *= 0.75
            else:
                col[:, :3] *= 0.8
            buf[off:off + n, 0:3] = pos
            buf[off:off + n, 3:6] = nor
            buf[off:off + n, 6:10] = col
            if not self._built:
                flip = _tri_orient(Pm, N, ni, nj)
                self._flip[key] = flip
        arr = self.vdata.modify_array(0)
        memoryview(arr).cast("B")[:] = np.ascontiguousarray(buf.ravel(), dtype=np.float32).tobytes()
        if not self._built:
            tris = []
            for key in self.order:
                ni, nj = self.shapes[key]
                tris.append(_grid_indices(ni, nj, self.offsets[key], self._flip[key]))
            allt = np.concatenate(tris).astype(np.int32)
            self.prim.add_vertices(*[0, 0, 0])
            self.prim.clear_vertices()
            self.prim.set_index_type(Geom.NT_uint32)
            parr = self.prim.modify_vertices()
            parr.unclean_set_num_rows(len(allt) * 3)
            memoryview(parr).cast("B")[:] = np.ascontiguousarray(allt.ravel(), dtype=np.uint32).tobytes()
            self.prim.set_nonindexed_vertices if False else None
            self.geom_obj.add_primitive(self.prim)
            self.node.add_geom(self.geom_obj)
            self._built = True
        else:
            self.node.mark_bounds_stale()


# ----------------------------------------------------------------------------
def make_cylinder(radius=1.0, length=1.0, seg=16, color=(1, 1, 1, 1), cap_front=True, cap_back=True,
                  nose=0.0, name="cyl"):
    """Cylinder along +X from x=-length to 0. nose>0: a cone of length nose on the front end (same units)."""
    ang = np.linspace(0, 2 * np.pi, seg + 1)
    cy, sy = np.cos(ang), np.sin(ang)
    pos, nor, idx = [], [], []
    x0, x1 = -length, 0.0
    # side surface
    b = len(pos)
    for i in range(seg + 1):
        pos.append((x0, radius * cy[i], radius * sy[i])); nor.append((0, cy[i], sy[i]))
        pos.append((x1, radius * cy[i], radius * sy[i])); nor.append((0, cy[i], sy[i]))
    for i in range(seg):
        a = b + 2 * i
        idx += [(a, a + 2, a + 1), (a + 1, a + 2, a + 3)]
    if nose > 0:
        b = len(pos)
        sl = radius / math.hypot(radius, nose)
        cs = nose / math.hypot(radius, nose)
        for i in range(seg + 1):
            pos.append((x1, radius * cy[i], radius * sy[i])); nor.append((sl, cs * cy[i], cs * sy[i]))
            pos.append((x1 + nose, 0, 0)); nor.append((sl, cs * cy[i], cs * sy[i]))
        for i in range(seg):
            a = b + 2 * i
            idx += [(a, a + 2, a + 1), (a + 1, a + 2, a + 3)]
    if cap_back:
        b = len(pos)
        pos.append((x0, 0, 0)); nor.append((-1, 0, 0))
        for i in range(seg + 1):
            pos.append((x0, radius * cy[i], radius * sy[i])); nor.append((-1, 0, 0))
        for i in range(seg):
            idx.append((b, b + 2 + i, b + 1 + i))
    if cap_front and nose <= 0:
        b = len(pos)
        pos.append((x1, 0, 0)); nor.append((1, 0, 0))
        for i in range(seg + 1):
            pos.append((x1, radius * cy[i], radius * sy[i])); nor.append((1, 0, 0))
        for i in range(seg):
            idx.append((b, b + 1 + i, b + 2 + i))
    vd = GeomVertexData(name, vformat(), Geom.UH_static)
    vd.set_num_rows(len(pos))
    arr = np.zeros((len(pos), 10), dtype=np.float32)
    arr[:, 0:3] = np.array(pos); arr[:, 3:6] = np.array(nor); arr[:, 6:10] = color
    memoryview(vd.modify_array(0)).cast("B")[:] = np.ascontiguousarray(arr.ravel(), dtype=np.float32).tobytes()
    prim = GeomTriangles(Geom.UH_static)
    prim.set_index_type(Geom.NT_uint32)
    ia = np.array(idx, dtype=np.uint32).ravel()
    parr = prim.modify_vertices()
    parr.unclean_set_num_rows(len(ia))
    memoryview(parr).cast("B")[:] = np.ascontiguousarray(ia, dtype=np.uint32).tobytes()
    g = Geom(vd)
    g.add_primitive(prim)
    gn = GeomNode(name)
    gn.add_geom(g)
    return NodePath(gn)


def make_box(sx, sy, sz, color=(1, 1, 1, 1), name="box"):
    """Box centred at the origin."""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    faces = [((1, 0, 0), [(hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz)]),
             ((-1, 0, 0), [(-hx, hy, -hz), (-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, hz)]),
             ((0, 1, 0), [(hx, hy, -hz), (-hx, hy, -hz), (-hx, hy, hz), (hx, hy, hz)]),
             ((0, -1, 0), [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz)]),
             ((0, 0, 1), [(-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]),
             ((0, 0, -1), [(-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz), (-hx, -hy, -hz)])]
    pos, nor, idx = [], [], []
    for n, vs in faces:
        b = len(pos)
        pos += vs; nor += [n] * 4
        idx += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    vd = GeomVertexData(name, vformat(), Geom.UH_static)
    vd.set_num_rows(len(pos))
    arr = np.zeros((len(pos), 10), dtype=np.float32)
    arr[:, 0:3] = np.array(pos); arr[:, 3:6] = np.array(nor); arr[:, 6:10] = color
    memoryview(vd.modify_array(0)).cast("B")[:] = np.ascontiguousarray(arr.ravel(), dtype=np.float32).tobytes()
    prim = GeomTriangles(Geom.UH_static)
    prim.set_index_type(Geom.NT_uint32)
    ia = np.array(idx, dtype=np.uint32).ravel()
    parr = prim.modify_vertices()
    parr.unclean_set_num_rows(len(ia))
    memoryview(parr).cast("B")[:] = np.ascontiguousarray(ia, dtype=np.uint32).tobytes()
    g = Geom(vd)
    g.add_primitive(prim)
    gn = GeomNode(name)
    gn.add_geom(g)
    return NodePath(gn)


class PointCloud:
    """Cloud of point particles with per-frame position and colour updates."""

    def __init__(self, n, name="particles", size=3.0):
        fmt = GeomVertexFormat.get_v3c4()
        self.n = n
        self.vd = GeomVertexData(name, fmt, Geom.UH_dynamic)
        self.vd.set_num_rows(n)
        self.prim = GeomPoints(Geom.UH_dynamic)
        self.prim.add_consecutive_vertices(0, n)
        self.prim.close_primitive()
        g = Geom(self.vd)
        g.add_primitive(self.prim)
        gn = GeomNode(name)
        gn.add_geom(g)
        self.np = NodePath(gn)
        self.np.set_render_mode_thickness(size)
        self.np.set_light_off()
        self.np.set_bin("fixed", 20)
        self.np.set_depth_write(False)
        self.buf = np.zeros((n, 4), dtype=np.float32)
        self.cbuf = np.zeros((n, 4), dtype=np.float32)
        # v3c4 format: c4 is stored as 4 uint8 bytes, hence a structured array
        self.dtype = np.dtype([("p", np.float32, 3), ("c", np.uint8, 4)])
        self.arr = np.zeros(n, dtype=self.dtype)

    def update(self, pos, col):
        n = self.n
        self.arr["p"][:] = pos
        self.arr["c"][:] = np.clip(col * 255, 0, 255).astype(np.uint8)
        memoryview(self.vd.modify_array(0)).cast("B")[:] = self.arr.tobytes()
