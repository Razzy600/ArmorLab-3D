"""3D scene: plates, projectile, jet, particles, camera."""
from __future__ import annotations
import math
import numpy as np
from panda3d.core import (NodePath, AmbientLight, DirectionalLight, Vec3, Vec4, Mat4, LineSegs,
                          TextNode, Point3, AntialiasAttrib, TransparencyAttrib, ColorBlendAttrib)

from .data import MATERIALS, CORES, AMMO, ERA_KEY, ERA_COLOR, ERA_FLYER_V
from .meshes import PlateMesh, make_cylinder, make_box, PointCloud
from .solver import Hole, expand_layers, plate_geom, RAD

STEEL_FLYER = (0.38, 0.39, 0.37)
EXPLOSIVE = (0.36, 0.42, 0.17)


def basis_matrix(ux, vx, wx, origin):
    """Matrix whose rows are the local axes expressed in world coordinates."""
    return Mat4(ux[0], ux[1], ux[2], 0,
                vx[0], vx[1], vx[2], 0,
                wx[0], wx[1], wx[2], 0,
                origin[0], origin[1], origin[2], 1)


def plate_axes(theta_deg):
    th = theta_deg * RAD
    u = (math.sin(th), 0.0, math.cos(th))
    v = (0.0, 1.0, 0.0)
    w = (-math.cos(th), 0.0, math.sin(th))
    return u, v, w


def dir_matrix(d, pos):
    d = np.array(d, dtype=float)
    d = d / (np.linalg.norm(d) + 1e-12)
    z = np.array([0, 0, 1.0])
    y = np.cross(z, d)
    if np.linalg.norm(y) < 1e-6:
        y = np.array([0, 1.0, 0])
    y /= np.linalg.norm(y)
    zz = np.cross(d, y)
    return basis_matrix(d, y, zz, pos)


def _att(parent, npath):
    npath.reparent_to(parent)
    return npath


class Particles:
    def __init__(self, nmax=4200):
        self.nmax = nmax
        self.cloud = PointCloud(nmax, size=3.0)
        self.np = self.cloud.np
        self.clear()

    def clear(self):
        self.P0 = np.zeros((0, 3)); self.V = np.zeros((0, 3)); self.tb = np.zeros(0)
        self.life = np.zeros(0); self.col = np.zeros((0, 3)); self.kind = np.zeros(0)
        self._chunks = []
        self.n = 0
        self._show(np.zeros((self.nmax, 3)) - 100, np.zeros((self.nmax, 4)))

    def emit(self, n, tb0, tb1, origin, axis, half_deg, vmin, vmax, life, color, jitter=0.004, rng=None, kind=0, spread=None):
        rng = rng or np.random.default_rng()
        axis = np.array(axis, dtype=float); axis /= np.linalg.norm(axis) + 1e-12
        a = np.array([0, 0, 1.0]) if abs(axis[2]) < 0.9 else np.array([0, 1.0, 0])
        e1 = np.cross(axis, a); e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        cs = np.cos(half_deg * RAD)
        ct = rng.uniform(cs, 1.0, n)
        st = np.sqrt(1 - ct ** 2)
        ph = rng.uniform(0, 2 * np.pi, n)
        d = axis[None, :] * ct[:, None] + st[:, None] * (np.cos(ph)[:, None] * e1 + np.sin(ph)[:, None] * e2)
        sp = rng.uniform(vmin, vmax, n)
        v = d * sp[:, None]
        jo = rng.normal(0, jitter, (n, 3))
        p = np.array(origin, dtype=float)[None, :] + jo
        tb = rng.uniform(tb0, max(tb1, tb0 + 1e-9), n)
        lf = rng.uniform(0.6, 1.0, n) * life
        c = np.array(color, dtype=float)[None, :] * rng.uniform(0.8, 1.1, (n, 1))
        self._chunks.append((p, v, tb, lf, c, np.full(n, kind)))

    def finalize(self):
        if not self._chunks:
            return
        P0 = np.concatenate([c[0] for c in self._chunks]); V = np.concatenate([c[1] for c in self._chunks])
        tb = np.concatenate([c[2] for c in self._chunks]); life = np.concatenate([c[3] for c in self._chunks])
        col = np.concatenate([c[4] for c in self._chunks]); kind = np.concatenate([c[5] for c in self._chunks])
        if len(P0) > self.nmax:
            sel = np.random.default_rng(1).choice(len(P0), self.nmax, replace=False)
            P0, V, tb, life, col, kind = P0[sel], V[sel], tb[sel], life[sel], col[sel], kind[sel]
        self.P0, self.V, self.tb, self.life, self.col, self.kind = P0, V, tb, life, col, kind
        self.n = len(P0)
        self._chunks = []

    def _show(self, pos, rgba):
        n = self.nmax
        p = np.zeros((n, 3)) - 100
        c = np.zeros((n, 4))
        k = len(pos)
        p[:k] = pos; c[:k] = rgba
        self.cloud.update(p, c)

    def at(self, t):
        if self.n == 0:
            return
        age = t - self.tb
        alive = (age >= 0) & (age < self.life)
        a = np.clip(age, 0, None)[:, None]
        pos = self.P0 + self.V * a
        f = np.clip(age / self.life, 0, 1)[:, None]
        hot = np.array([1.0, 0.92, 0.55])
        mid = self.col
        cool = np.array([0.22, 0.22, 0.24])
        rgb = np.where(self.kind[:, None] == 1,
                       mid * (1 - f) + cool * f,
                       np.where(f < 0.3, hot * (1 - f / 0.3) + mid * (f / 0.3), mid * (1 - (f - 0.3) / 0.7) + cool * ((f - 0.3) / 0.7)))
        alpha = np.where(alive, np.clip(1.4 - f[:, 0] * 1.2, 0, 1), 0.0)
        pos = np.where(alive[:, None], pos, -100.0)
        rgba = np.concatenate([rgb, alpha[:, None]], axis=1)
        self._show(pos, rgba)


class World:
    def __init__(self, base, font=None):
        self.base = base
        self.font = font
        self.root = base.render.attachNewNode("world")
        base.render.set_antialias(AntialiasAttrib.MAuto)
        self._lights()
        self._floor()
        self.plate_root = self.root.attachNewNode("plates")
        self.fx_root = self.root.attachNewNode("fx")
        self.label_root = self.root.attachNewNode("labels")
        self.items = []
        self.section = True
        self.show_labels = True
        self.res = None
        self.particles = Particles()
        self.particles.np.reparent_to(self.root)
        self.rod = None
        self.heat_nodes = None
        self.plug_np = []
        self.axis_np = None
        self.ammo = None
        try:
            base.camLens.set_fov(52)
            base.camLens.set_near_far(0.02, 60)
        except Exception:
            pass
        self.cam_target = Vec3(0.3, 0, 0)
        self.cam_az = -22.0
        self.cam_el = 14.0
        self.cam_dist = 1.8
        self.rng = np.random.default_rng(7)
        self.ric = None
        self.stack_len = 0.2
        self.t_pre = 0.0
        self.t_post = 0.0
        self.t_total = (0.0, 1.0)

    # ------------------------------------------------------------------
    def _lights(self):
        a = AmbientLight("amb"); a.set_color(Vec4(0.42, 0.44, 0.48, 1))
        self.root.set_light(self.root.attach_new_node(a))
        d = DirectionalLight("key"); d.set_color(Vec4(1.0, 0.96, 0.9, 1))
        dn = self.root.attach_new_node(d); dn.set_hpr(-35, -42, 0)
        self.root.set_light(dn)
        d2 = DirectionalLight("fill"); d2.set_color(Vec4(0.35, 0.42, 0.55, 1))
        dn2 = self.root.attach_new_node(d2); dn2.set_hpr(140, -20, 0)
        self.root.set_light(dn2)
        d3 = DirectionalLight("rim"); d3.set_color(Vec4(0.45, 0.45, 0.5, 1))
        dn3 = self.root.attach_new_node(d3); dn3.set_hpr(75, -10, 0)
        self.root.set_light(dn3)
        try:
            if self.base.win.get_gsg().supports_basic_shaders():
                self.base.render.set_shader_auto()
        except Exception:
            pass

    def _floor(self):
        ls = LineSegs("grid")
        ls.set_thickness(1.0)
        z = -0.62
        n = 16
        for i in range(-n, n + 1):
            c = 0.20 if i % 4 else 0.30
            ls.set_color(c * 0.6, c * 0.75, c, 1)
            ls.move_to(i * 0.25, -n * 0.25, z); ls.draw_to(i * 0.25, n * 0.25, z)
            ls.move_to(-n * 0.25, i * 0.25, z); ls.draw_to(n * 0.25, i * 0.25, z)
        g = self.root.attach_new_node(ls.create())
        g.set_light_off()

    # ------------------------------------------------------------------
    def clear_scene(self):
        for it in self.items:
            it["np"].remove_node()
        self.items = []
        self.label_root.remove_node()
        self.label_root = self.root.attach_new_node("labels")
        if self.rod:
            self.rod["root"].remove_node(); self.rod = None
        if self.heat_nodes:
            self.heat_nodes["root"].remove_node(); self.heat_nodes = None
        for p in self.plug_np:
            p.remove_node()
        self.plug_np = []
        self.plugs = []
        if self.axis_np:
            self.axis_np.remove_node(); self.axis_np = None
        self.particles.clear()
        self.res = None

    def build(self, ammo_key, layers, yaw, standoff, witness, witness_gap, section, labels=True):
        self.clear_scene()
        self.section = section
        self.show_labels = labels
        a = AMMO[ammo_key]
        self.ammo = a
        kobl = 0.9 if (a.cls != "heat" and a.nose == "pointed") else 1.0
        wt = 1.2 if a.cls == "heat" else 0.8
        self.dc = (a.d_mm / 1000.0) if a.cls != "heat" else 0.35 * a.d_mm / 1000.0
        slabs = expand_layers(layers, 0.0 if a.cls == "heat" else yaw, kobl, witness, witness_gap, witness_t=wt, dc=self.dc)
        self.slabs = slabs
        self.standoff = standoff
        n_real = [s for s in slabs if s.role != "witness"]
        self.stack_len = (slabs[-1].s_front + slabs[-1].T) if slabs else 0.1
        self._lbl_used = []
        self._build_items(slabs, layers, section)
        self._build_actor(a, standoff)
        # line of fire
        ls = LineSegs("axis"); ls.set_thickness(1.0)
        x0 = -(standoff + 0.2) if a.cls == "heat" else -1.0
        x1 = self.stack_len + 0.4
        ls.set_color(0.2, 0.75, 0.8, 0.7)
        n = 40
        for i in range(n):
            if i % 2 == 0:
                ls.move_to(x0 + (x1 - x0) * i / n, 0, 0); ls.draw_to(x0 + (x1 - x0) * (i + 1) / n, 0, 0)
        self.axis_np = self.root.attach_new_node(ls.create()); self.axis_np.set_light_off()
        self.set_time(-1.0)

    def _build_items(self, slabs, layers, section):
        i = 0
        while i < len(slabs):
            sl = slabs[i]
            u, v, w = plate_axes(sl.angle)
            if sl.role == "flyer":
                s2 = slabs[i + 1]
                lay = layers[sl.parent]
                self._add_era(sl, s2, lay, i)
                i += 2
                continue
            if sl.role == "witness":
                t = 0.2
                g = dict(shape="rect", ul=0.25, ur=0.25, vd=0.25, vu=0.25)
                origin = (sl.s_front, 0, 0)
                hit = True
            else:
                lay = layers[sl.parent]
                pg = plate_geom(lay, self.dc)
                t = sl.t
                hit = pg["hit"]
                if hit:
                    g = pg
                    origin = (sl.s_front, 0, 0)
                else:
                    if pg["shape"] == "round":
                        g = dict(shape="round", R=pg["R"], ou=0.0, ov=0.0)
                    else:
                        g = dict(shape="rect", ul=pg["Hh"] / 2, ur=pg["Hh"] / 2, vd=pg["W"] / 2, vu=pg["W"] / 2)
                    origin = (sl.s_front + lay.ou * u[0] + lay.ov * v[0], lay.ov * v[1] + lay.ou * u[1],
                              lay.ou * u[2] + lay.ov * v[2])
            m = MATERIALS[sl.mat]
            pm = PlateMesh(t, sl.angle, g, m.color, section=section and hit, seed=17 + i)
            pm.update(None, 0.0)
            np_ = self.plate_root.attach_new_node(pm.node)
            np_.set_mat(basis_matrix(u, v, w, origin))
            if sl.role != "witness" and layers[sl.parent].dmg > 0.01:
                dm = min(layers[sl.parent].dmg, 1.0)
                np_.set_color_scale(1 - 0.40 * dm, 1 - 0.50 * dm, 1 - 0.55 * dm, 1)     # a damaged layer is darker
            it = dict(kind="witness" if sl.role == "witness" else "plate", pm=pm, np=np_, slab=i, t=t,
                      theta=sl.angle, s_front=sl.s_front, T=sl.T, last_p=-1.0, hole=None, geom=g, hit=hit, origin=origin)
            self.items.append(it)
            if self.show_labels:
                if sl.role == "witness":
                    self._text('RHA witness plate', (sl.s_front, 0, 0.30))
                else:
                    self._label(sl, lay, i)
            i += 1

    def _free_pos(self, pos, step=0.07):
        """Moves the label up if another one is already nearby (adjacent thin layers)."""
        x, y, z = pos
        for _ in range(12):
            if any(abs(x - px) < 0.35 and abs(z - pz) < step * 0.9 for px, pz in self._lbl_used):
                z += step
            else:
                break
        self._lbl_used.append((x, z))
        return (x, y, z)

    def _text(self, s, pos, scale=0.028, color=(0.85, 0.9, 0.95, 1)):
        tn = TextNode("lbl")
        if self.font:
            tn.set_font(self.font)
        tn.set_text(s)
        tn.set_align(TextNode.ACenter)
        tn.set_text_color(*color)
        tn.set_shadow(0.04, 0.04); tn.set_shadow_color(0, 0, 0, 0.9)
        np_ = self.label_root.attach_new_node(tn)
        np_.set_pos(*pos); np_.set_scale(scale)
        np_.set_python_tag("pos", pos)
        np_.set_billboard_point_eye()
        np_.set_light_off(); np_.set_depth_test(False); np_.set_bin("fixed", 30)
        return np_

    def _label_pos(self, lay, sl):
        u, v, w = plate_axes(sl.angle)
        g = plate_geom(lay, self.dc)
        d = lay.ou + g["Hh"] / 2 if g["shape"] != "round" else lay.ou + g["W"] / 2
        return (sl.s_front + d * u[0], lay.ov, d * u[2] + 0.045)

    def _label(self, sl, lay, idx):
        short = sl.mat
        miss = '  (miss)' if sl.miss else ""
        s = '%d  %s  %d mm  @%d°%s' % (sl.parent + 1, short, round(lay.t * 1000), round(lay.angle), miss)
        self._text(s, self._free_pos(self._label_pos(lay, sl)), color=(0.62, 0.66, 0.7, 1) if sl.miss else (0.85, 0.9, 0.95, 1))

    def _add_era(self, s1, s2, lay, idx):
        theta = s1.angle
        t = lay.t
        tf = s1.t
        g = plate_geom(lay, self.dc)
        W, Hh = g["W"], g["Hh"]
        root = self.plate_root.attach_new_node("era")
        u, v, w = plate_axes(theta)
        root.set_mat(basis_matrix(u, v, w, (s1.s_front, 0, 0)))
        parts = []
        for name, z0, z1, col in (("f1", 0.0, -tf, STEEL_FLYER), ("ex", -tf, -(t - tf), EXPLOSIVE), ("f2", -(t - tf), -t, STEEL_FLYER)):
            b = make_box(Hh, W, abs(z1 - z0), color=col + (1,))
            nb = _att(root, b)
            nb.set_pos(lay.ou, lay.ov, 0.5 * (z0 + z1))
            parts.append(nb)
        it = dict(kind="era", np=root, parts=parts, slab=idx, t=t, theta=theta, s_front=s1.s_front, T=0,
                  active_t=None, w=w, tf=tf, ou=lay.ou, ov=lay.ov)
        self.items.append(it)
        if self.show_labels:
            miss = '  (miss)' if s1.miss else ""
            self._text('%d  ERA  %d mm  @%d°%s' % (s1.parent + 1, round(t * 1000), round(theta), miss),
                       self._free_pos(self._label_pos(lay, s1)), color=(0.9, 0.95, 0.6, 1))

    def _build_actor(self, a, standoff):
        if a.cls == "heat":
            D = a.d_mm / 1000.0
            root = self.fx_root.attach_new_node("heat")
            body = make_cylinder(radius=D / 2, length=3 * D, seg=28, color=(0.42, 0.45, 0.40, 1), nose=0.0)
            bn = _att(root, body); bn.set_pos(-standoff, 0, 0)
            cone = make_cylinder(radius=D / 2, length=1e-5, seg=28, color=(0.75, 0.42, 0.25, 1), nose=-0.0)
            # copper liner: the truncated cone is drawn as a short cylinder
            fun = make_cylinder(radius=D / 2 * 0.98, length=0.35 * D, seg=28, color=(0.78, 0.42, 0.22, 1))
            fn = _att(root, fun); fn.set_pos(-standoff + 0.35 * D, 0, 0)
            jn = root.attach_new_node("jet")
            slugs = []
            NS = 36
            for k in range(NS):
                sg = _att(jn, make_cylinder(radius=1.0, length=1.0, seg=8, color=(1, 1, 1, 1)))
                f = k / (NS - 1.0)
                sg.set_color(1.0, 0.97 - 0.30 * f, 0.80 - 0.55 * f, 1)      # white head, orange tail
                sg.set_light_off()
                slugs.append(sg)
            jn.hide()
            self.heat_nodes = dict(root=root, body=bn, jet=jn, D=D, slugs=slugs)
        else:
            d = a.d_mm / 1000.0
            r = d / 2
            core = CORES[a.core]
            root = self.fx_root.attach_new_node("rod")
            body = make_cylinder(radius=1, length=1, seg=18, color=(1, 1, 1, 1))
            bn = _att(root, body)
            nose = make_cylinder(radius=1, length=1e-5, seg=18, color=(1, 1, 1, 1), nose=1.0)
            nn = _att(root, nose)
            for n_ in (bn, nn):
                n_.set_color(*core.color, 1)
            self.rod = dict(root=root, body=bn, nose=nn, r=r, d=d, L0=a.L_mm / 1000.0,
                            nose_len=(1.7 if a.nose == "pointed" else 0.7) * d)

    # ------------------------------------------------------------------
    def frame_camera(self):
        a = self.ammo
        x0 = -(self.standoff + 0.25) if a.cls == "heat" else -0.5
        x1 = self.stack_len + 0.2
        self.cam_target = Vec3((x0 + x1) * 0.5 + 0.1, 0, 0)
        self.cam_dist = max(1.4, (x1 - x0) * 1.9)
        self.apply_camera()

    def frame_impact(self):
        self.cam_target = Vec3(0.0, 0, 0)
        self.cam_dist = 0.55
        self.apply_camera()

    def apply_camera(self):
        az, el = math.radians(self.cam_az), math.radians(self.cam_el)
        d = self.cam_dist
        off = Vec3(math.sin(az) * math.cos(el) * d, -math.cos(az) * math.cos(el) * d, math.sin(el) * d)
        self.base.camera.set_pos(self.cam_target + off)
        self.base.camera.look_at(self.cam_target)
        k = 0.014 * d
        for ch in self.label_root.get_children():
            ch.set_scale(max(min(k, 0.05), 0.006))

    # ------------------------------------------------------------------
    def load_result(self, res):
        """Prepare the animation from the solver result."""
        self.res = res
        a = self.ammo
        P = self.particles
        P.clear()
        rng = np.random.default_rng(3)
        slabs = res.slabs
        defs = res.slab_defs
        # final holes
        for it in self.items:
            it["hole"] = None
            it["last_p"] = -1.0
            if it["kind"] in ("plate", "witness"):
                sr = slabs[it["slab"]]
                h = sr.hole
                if h is not None and it["kind"] == "witness":
                    h = self._witness_hole(it, sr)
                it["hole"] = h
                it["sr"] = sr
                it["ultra"] = res.mode == "ULTRA"
            elif it["kind"] == "era":
                it["active_t"] = None
        for ev in res.events:
            if ev["kind"] == "era":
                for it in self.items:
                    if it["kind"] == "era" and it["slab"] == ev["slab"]:
                        it["active_t"] = ev["t"]
        # animation time
        if a.cls == "heat":
            self.t_pre = -20e-6
        else:
            self.t_pre = -0.30 / a.v
        self.t_post = 0.0
        t_end = res.t_end
        if a.cls != "heat":
            if not res.ricochet and res.verdict == 'PENETRATED':
                t_end += 0.35 / max(res.v_res, 300)
            elif res.ricochet:
                t_end += 0.3 / max(res.ric_v, 300)
        else:
            t_end *= 1.05
        self.t_total = (self.t_pre, max(t_end, 20e-6))
        # particles
        for j, sr in enumerate(slabs):
            sl = defs[j]
            if sl.role == "flyer":
                continue
            u, v, w = plate_axes(sl.angle)
            nout = np.array(w)
            sf = sl.s_front
            if sr.depth > 0 and sr.v_in > 0:
                n = 160 if a.cls == "heat" else 120
                for ev in res.events:
                    if ev["kind"] == "splash" and ev["slab"] == j:
                        n = ev["n"]
                t0 = sr.t_hit
                t1 = max(sr.t_exit, t0 + 5e-6)
                vv = sr.v_in
                P.emit(n, t0, t1, (sf, 0, 0), nout, 62, 0.08 * vv, 0.55 * vv, 0.5e-3, (0.95, 0.5, 0.15), 0.004, rng)
                if a.cls == "heat":
                    P.emit(40, t0, t1, (sf, 0, 0), nout, 28, 0.2 * vv, 0.7 * vv, 0.4e-3, (1.0, 0.8, 0.4), 0.002, rng)
            if sr.perforated and sr.depth > 0:
                tx = sr.t_exit
                s_exit = sf + sl.T
                fwd = np.array([1.0, 0, 0])
                nsp = sr.spall_n
                if nsp:
                    P.emit(nsp, tx, tx + 30e-6, (s_exit, 0, 0), fwd, 38, 0.25 * max(sr.v_out, 300), 0.9 * max(sr.v_out, 300),
                           0.9e-3, (0.9, 0.4, 0.12), 0.004, rng, kind=1)
                if a.cls != "heat":
                    nd = int(min(60, 12 + 20 * (sr.v_out > 200)))
                    P.emit(nd, tx, tx + 25e-6, (s_exit, 0, 0), fwd, 16, 0.4 * max(sr.v_out, 300), 1.0 * max(sr.v_out, 300),
                           0.8e-3, (0.85, 0.55, 0.25), 0.003, rng)
        for ev in res.events:
            if ev["kind"] == "era":
                it = next(i for i in self.items if i["kind"] == "era" and i["slab"] == ev["slab"])
                w = np.array(it["w"])
                c = np.array([it["s_front"], 0, 0])
                P.emit(140, ev["t"], ev["t"] + 40e-6, c, w, 80, 120, 650, 0.45e-3, (1.0, 0.65, 0.2), 0.02, rng)
                P.emit(80, ev["t"], ev["t"] + 40e-6, c, -w, 80, 120, 650, 0.45e-3, (1.0, 0.6, 0.2), 0.02, rng)
            if ev["kind"] == "ricochet":
                it = self.items[0]
                P.emit(90, ev["t"], ev["t"] + 40e-6, (ev["s"], 0, 0), np.array(res.ric_dir), 40, 0.1 * a.v, 0.45 * a.v,
                       0.6e-3, (1.0, 0.8, 0.4), 0.003, rng)
        P.finalize()
        # plugs
        for p in self.plug_np:
            p.remove_node()
        self.plug_np = []
        self.plugs = []
        for ev in res.events:
            if ev["kind"] == "plug":
                j = ev["slab"]
                sl = defs[j]
                sr = slabs[j]
                r = (a.d_mm / 2000.0) * 1.1
                cyl = make_cylinder(radius=1, length=1, seg=14, color=(1, 1, 1, 1))
                n_ = _att(self.fx_root, cyl)
                n_.set_color(*MATERIALS[sl.mat].color, 1)
                n_.set_scale(sl.t, r, r)
                n_.hide()
                self.plug_np.append(n_)
                self.plugs.append(dict(np=n_, t=ev["t"], s=sl.s_front + sl.T, v=ev["v"], len=sl.t))
        self.set_time(self.t_pre)

    def _witness_hole(self, it, sr):
        T = sr.T
        td = float(np.clip(1.25 * sr.depth, 0.1, 1.0))
        it["pm_t"] = td
        h = sr.hole
        k = h.k * T / td
        newh = Hole(k=np.clip(k, 0, 1), r=h.r.copy(), lip=h.lip, dish=h.dish, bulge=0.0, perforated=False)
        # rebuild the plate with the required thickness
        old = it["pm"]
        if abs(old.t - td) > 1e-4:
            pm = PlateMesh(td, 0.0, it["geom"], MATERIALS["RHA"].color, section=self.section, seed=99)
            pm.update(None, 0.0)
            it["np"].remove_node()
            np_ = self.plate_root.attach_new_node(pm.node)
            u, v, w = plate_axes(0.0)
            np_.set_mat(basis_matrix(u, v, w, (it["s_front"], 0, 0)))
            it["pm"] = pm
            it["np"] = np_
        return newh

    # ------------------------------------------------------------------
    def set_time(self, t):
        res = self.res
        a = self.ammo
        if a is None:
            return
        # plate progress
        if res is not None:
            tr = res.track
            tip_s = float(np.interp(t, tr["t"], tr["s"])) if t >= 0 else -1e9
            if a.cls == "heat" and t >= 0:
                tip_s = float(np.interp(t, tr["t"], tr["s"]))
            for it in self.items:
                if it["kind"] in ("plate", "witness"):
                    h = it["hole"]
                    sr = it["sr"]
                    if h is None or sr.depth <= 0:
                        continue
                    if t > res.t_end:
                        p = 1.0
                    elif t < sr.t_hit:
                        p = 0.0
                    else:
                        den = sr.depth if it["kind"] == "plate" else sr.depth
                        p = float(np.clip((tip_s - it["s_front"]) / max(den, 1e-9), 0, 1))
                    if abs(p - it["last_p"]) > 0.004 or (p in (0.0, 1.0) and it["last_p"] != p):
                        it["pm"].update(h if p > 0 else None, p if p > 0 else 0.0, ultra=it.get("ultra", True),
                                        heat=0.6 * max(0.0, 1 - (t - sr.t_hit) / 3e-3) if p > 0 else 0.0)
                        it["last_p"] = p
                elif it["kind"] == "era":
                    at = it["active_t"]
                    tf = it["tf"]
                    if at is not None and t > at:
                        dt = t - at
                        mv = ERA_FLYER_V * dt
                        it["parts"][0].set_pos(it["ou"], it["ov"], -0.5 * tf + mv)
                        it["parts"][2].set_pos(it["ou"], it["ov"], -it["t"] + 0.5 * tf - mv)
                        it["parts"][0].set_p(min(dt * 3000, 25))
                        it["parts"][2].set_p(-min(dt * 3000, 25))
                        it["parts"][1].hide()
                    else:
                        it["parts"][0].set_pos(it["ou"], it["ov"], -0.5 * tf); it["parts"][0].set_p(0)
                        it["parts"][1].set_pos(it["ou"], it["ov"], -0.5 * it["t"]); it["parts"][1].show()
                        it["parts"][2].set_pos(it["ou"], it["ov"], -it["t"] + 0.5 * tf); it["parts"][2].set_p(0)
        self._update_actor(t)
        self.particles.at(t)
        # plugs
        for pg in getattr(self, "plugs", []):
            if t >= pg["t"]:
                x = pg["s"] + pg["v"] * (t - pg["t"]) + 0.5 * pg["len"]
                pg["np"].set_pos(x, 0, 0)
                pg["np"].show()
            else:
                pg["np"].hide()

    def _update_actor(self, t):
        a = self.ammo
        res = self.res
        if a.cls == "heat":
            hn = self.heat_nodes
            if not hn:
                return
            D = hn["D"]
            if res is None or t < 0:
                hn["jet"].hide()
                return
            S = self.standoff
            vt, vmin = a.vt, a.vmin
            tr = res.track
            tc = S / vt
            x_tail = -S + vmin * t
            if t < tc:
                x_tip = -S + vt * t
            else:
                x_tip = float(np.interp(t, tr["t"], tr["s"]))
            end_cut = res.t_end
            if x_tail <= x_tip + 1e-4 or t > end_cut:
                if t > end_cut * 1.0:
                    hn["jet"].hide(); return
            ln = max(x_tail - x_tip, 1e-4)
            if x_tip < x_tail:
                hn["jet"].show()
                # jet of links: thin head, thicker tail; after the breakup time the links tear apart (particles)
                tb = res.jet.get("tb", 1e-4) if res.jet else 1e-4
                g = float(np.clip((t - tb) / (2.0 * tb), 0.0, 1.0))
                sg_list = hn["slugs"]
                n_s = len(sg_list)
                seg = ln / n_s
                for k, sg in enumerate(sg_list):
                    f = k / (n_s - 1.0)
                    gap = g * (0.35 + 0.5 * f)
                    sl_len = max(seg * (1.0 - gap), 1e-5)
                    rad = D * (0.010 + 0.016 * f) * (1.0 - 0.35 * g)
                    sg.set_scale(sl_len, rad, rad)
                    sg.set_pos(x_tip + (k + 1) * seg, 0, 0)
            else:
                hn["jet"].hide()
        else:
            rd = self.rod
            if not rd:
                return
            L0, d = rd["L0"], rd["d"]
            if res is None:
                x_tip = -0.30
                L = L0
                dirv = (1, 0, 0)
                pos = (x_tip, 0, 0)
            else:
                tr = res.track
                if t < 0:
                    x_tip = a.v * t
                    L = L0
                    pos = (x_tip, 0, 0); dirv = (1, 0, 0)
                elif res.ricochet:
                    s0 = tr["s"][0]
                    dirv = res.ric_dir
                    tt = t
                    pos = tuple(np.array(dirv) * res.ric_v * tt)
                    L = float(tr["L"][-1])
                elif t <= tr["t"][-1]:
                    x_tip = float(np.interp(t, tr["t"], tr["s"]))
                    L = float(np.interp(t, tr["t"], tr["L"]))
                    pos = (x_tip, 0, 0); dirv = (1, 0, 0)
                else:
                    x_end = float(tr["s"][-1])
                    L = float(tr["L"][-1])
                    if res.verdict == 'PENETRATED':
                        x_tip = x_end + res.v_res * (t - tr["t"][-1])
                    else:
                        x_tip = x_end
                    pos = (x_tip, 0, 0); dirv = (1, 0, 0)
            L = max(L, 0.0)
            nl = min(rd["nose_len"], L)
            Lb = max(L - nl, 1e-6)
            rd["root"].set_mat(dir_matrix(dirv, pos))
            er = float(np.clip((L0 - L) / max(L0, 1e-9), 0.0, 1.0)) if (res is not None and t >= 0) else 0.0
            flare = 1.0 + 0.9 * min(er * 2.5, 1.0)         # "mushroomed" head of the eroding rod
            nl_v = nl * (1.0 - 0.5 * min(er * 2.5, 1.0))
            Lb = max(L - nl_v, 1e-6)
            rd["nose"].set_pos(-nl_v, 0, 0); rd["nose"].set_scale(nl_v, rd["r"] * flare, rd["r"] * flare)
            rd["body"].set_pos(-nl_v, 0, 0); rd["body"].set_scale(Lb, rd["r"], rd["r"])
            if L < 0.0015:
                rd["root"].hide()
            else:
                rd["root"].show()

    def reset_view_only(self):
        for it in self.items:
            if it["kind"] in ("plate", "witness"):
                it["pm"].update(None, 0.0)
                it["last_p"] = -1.0
            elif it["kind"] == "era":
                it["active_t"] = None
        for pg in getattr(self, "plugs", []):
            pg["np"].hide()
