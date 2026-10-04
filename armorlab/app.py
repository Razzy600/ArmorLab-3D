"""ArmorLab 3D main window."""
from __future__ import annotations
import json
import math
import os
import re
import sys
import textwrap
import time
import traceback

from panda3d.core import loadPrcFileData, Filename, TextNode

OFFSCREEN = bool(os.environ.get("ARMORLAB_OFFSCREEN"))
loadPrcFileData("", "window-title ArmorLab 3D\nwin-size 1600 940\ntext-encoding utf8\nsync-video 1\n"
                    "framebuffer-multisample 1\nmultisamples 4\ngl-check-errors 0\n")
if OFFSCREEN:
    loadPrcFileData("", "window-type offscreen\nload-display p3tinydisplay\nwin-size 1600 940\n")

from direct.showbase.ShowBase import ShowBase
from direct.gui import DirectGuiGlobals as DGG
from direct.gui.DirectGui import DirectFrame

from . import data as D
from . import calc as C
from . import analysis as AN
from . import series as SR
from . import solver as SV
from .data import (MATERIALS, MATERIAL_ORDER, ERA_KEY, ERA_NAME, ERA_COLOR, AMMO, AMMO_ORDER, CORES, KINDS,
                   rod_mass, Material)
from .solver import Layer, solve, MODES, plate_geom
from .scene3d import World
from .ui import (UI, SliderRow, Dropdown, BG, BG2, BG3, LINE, FG, DIM, ACCENT, TEAL, RED, GREEN, BLUE, CLEAR, shade)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_MATS = os.path.join(ROOT, "materials_user.json")
SCENES = os.path.join(ROOT, "scenes")
MAX_LAYERS = 24
ROWS = 8
LW = 1.02      # left panel width
RW = 1.06      # right panel width

UI_FONTS = [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\tahoma.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf"]
MONO_FONTS = [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/Library/Fonts/Courier New.ttf"]

MODE_HELP = {
    "NORMAL": 'Quick calculation: coarse step, simple hole shape.',
    "ADVANCED": 'Fine time step, per-layer energy, explosive reactive armor.',
    "ULTRA": 'Plus morphology: crater, lip, bulge, petals, plug, spall.',
}


PRESETS = [
    ('Stack: SiC 80 + gap 30 + RHA 350', dict(
        ammo="M829A1", layers=[Layer("SIC", 0.080, 0, 0.030), Layer("RHA", 0.350, 0, 0.0)], mode="ULTRA")),
    ('Stack: B4C 80 + gap 30 + RHA 350', dict(
        ammo="M829A1", layers=[Layer("B4C", 0.080, 0, 0.030), Layer("RHA", 0.350, 0, 0.0)], mode="ULTRA")),
    ('RHA: M829A1 → 500 mm, 0°', dict(
        ammo="M829A1", layers=[Layer("RHA", 0.500, 0, 0.0)], mode="ULTRA")),
    ('RHA: M2AP bullet → 20 mm, 0°', dict(
        ammo="M2AP", layers=[Layer("RHA", 0.020, 0, 0.0)], mode="ULTRA")),
    ('APFSDS M829A1 → ERA + sloped armor', dict(
        ammo="M829A1", layers=[Layer(ERA_KEY, 0.040, 60, 0.05), Layer("RHA", 0.300, 60, 0.0)], mode="ULTRA")),
    ('APFSDS DM53 → composite armor with ceramic', dict(
        ammo="DM53", layers=[Layer("RHA", 0.060, 0, 0.0), Layer("SIC", 0.100, 0, 0.0),
                             Layer("RHA", 0.060, 0, 0.0), Layer("UHMWPE", 0.080, 0, 0.0)], mode="ULTRA")),
    ('APFSDS 3BM42 → RHA plate 250 mm, 30°', dict(
        ammo="3BM42", layers=[Layer("RHA", 0.250, 30, 0.0)], mode="ULTRA")),
    ('B-32 bullet → RHA 20 mm, 0° (penetration)', dict(
        ammo="B32", layers=[Layer("RHA", 0.020, 0, 0.0)], mode="ULTRA")),
    ('B-32 bullet → RHA 20 mm, 72° (ricochet)', dict(
        ammo="B32", layers=[Layer("RHA", 0.020, 72, 0.0)], mode="ULTRA")),
    ('APFSDS 3BM42 → thin plate 15 mm (petals)', dict(
        ammo="3BM42", layers=[Layer("RHA", 0.015, 0, 0.0)], mode="ULTRA")),
    ('M2 AP bullet → 12 mm HHS (plugging)', dict(
        ammo="M2AP", layers=[Layer("HHS", 0.012, 0, 0.0)], mode="ULTRA")),
    ('TOW-2A → ERA + spaced armor', dict(
        ammo="TOW2A", layers=[Layer(ERA_KEY, 0.040, 60, 0.15), Layer("RHA", 0.060, 0, 0.30),
                              Layer("RHA", 0.100, 0, 0.0)], mode="ULTRA", standoff_cd=6.0)),
    ('PG-7V → RHA 350 mm', dict(
        ammo="PG7", layers=[Layer("RHA", 0.350, 0, 0.0)], mode="ULTRA", standoff_cd=5.5)),
    ('Hellfire → ceramic + aluminum', dict(
        ammo="HELLFIRE", layers=[Layer("AL7039", 0.060, 0, 0.0), Layer("B4C", 0.080, 0, 0.0),
                                 Layer("AL5083", 0.060, 0, 0.0), Layer("RHA", 0.150, 0, 0.0)], mode="ULTRA", standoff_cd=6.0)),
]



def _font(loader, cands):
    for p in cands:
        if os.path.exists(p):
            try:
                f = loader.load_font(str(Filename.from_os_specific(p)))
                f.set_pixels_per_unit(72)
                f.set_page_size(512, 512)
                return f
            except Exception:
                pass
    return None


def mat_color(key):
    if key == ERA_KEY:
        return ERA_COLOR + (1,)
    m = MATERIALS.get(key)
    return (m.color + (1,)) if m else (0.5, 0.5, 0.5, 1)


def mat_name(key):
    if key == ERA_KEY:
        return ERA_NAME
    m = MATERIALS.get(key)
    return (('[custom] ' if m.user else "") + m.name) if m else key


class App(ShowBase):
    def __init__(self, shot=None):
        ShowBase.__init__(self)
        self.disable_mouse()
        self.set_background_color(0.050, 0.062, 0.080, 1)
        D.load_user_materials(USER_MATS)
        self.font = _font(self.loader, UI_FONTS)
        self.mono = _font(self.loader, MONO_FONTS) or self.font
        self.ui = UI(self, self.font, self.mono)
        self.world = World(self, self.font)
        self.ammo_key = "M829A1"
        self.v = AMMO["M829A1"].v
        self.yaw = 0.0
        self.standoff_cd = 6.0
        self.witness_gap = 0.05
        self.layers = []
        self.sel = 0
        self.list_off = 0
        self.mode = "ULTRA"
        self.witness = True
        self.section = True
        self.labels = True
        self.result = None
        self.playing = False
        self.paused = False
        self.wall_t = 0.0
        self.duration = 9.0
        self._rebuild_job = None
        self._drag = None
        self.shot = shot
        self.tab = "target"
        self.edit_page = "layer"
        self.scene_name = 'my_scene'
        self.scene_files = []
        self.scene_sel = -1
        self.scene_off = 0
        self.mat_edit_key = "RHA"
        self._med = {}
        self.cond = dict(temp=20.0, por=0.0, cycles=1.0)
        self.mc = None
        self.mc_cfg = dict(n=60, s_rho=5.0, s_str=10.0)
        self.ser_cfg = dict(n=10, sigma=30.0, k=1.0, runs=8)
        self.ser = None
        self.ser_stats = None
        self.dmap_on = False
        self.dmap_layer = 0
        self.dmap_nodes = []
        self.chart_on = False
        self.chart_idx = 0
        self.chart_nodes = []
        self.mass_cache = None
        self.shots = 0
        self._build_gui()
        self._bind()
        self.load_preset(0)
        self.task_mgr.add(self._tick, "tick")
        if shot:
            self.task_mgr.do_method_later(0.05, self._shot_task, "shot")

    # ================================================================== GUI
    def _build_gui(self):
        ui = self.ui
        L = self.a2dTopLeft
        R = self.a2dTopRight
        self.left = ui.panel(L, (0, LW, -2.2, 0))
        self.right = ui.panel(R, (-RW, 0, -2.2, 0))
        p = self.left
        self.x0 = 0.04
        self.ww = LW - 0.08
        x0, ww = self.x0, self.ww
        ui.label(p, "ARMORLAB 3D", (x0, -0.07), 0.058, ACCENT)
        ui.label(p, 'engineering armor simulator', (x0, -0.108), 0.028, DIM)
        # tabs
        self.tab_btns = {}
        tabs = [("target", 'Target'), ("ammo", 'Ammo'), ("mats", 'Mats'), ("scenes", 'Scenes'), ("calc", 'Calcs'),
                ("cond", 'Cond.'), ("def", 'Defects'), ("ana", 'Stats'), ("ser", 'Series')]
        bw = (ww - 8 * 0.008) / 9
        for i, (k, n) in enumerate(tabs):
            self.tab_btns[k] = ui.button(p, n, (x0 + i * (bw + 0.008), -0.18), (bw, 0.058), self.set_tab, scale=0.0225,
                                         extra=dict(extraArgs=[k]))
        ui.hline(p, x0, LW - 0.04, -0.222)
        self.g = {k: ui.group(p) for k, _ in tabs}
        self._tab_target(self.g["target"])
        self._tab_ammo(self.g["ammo"])
        self._tab_mats(self.g["mats"])
        self._tab_scenes(self.g["scenes"])
        self._tab_calc(self.g["calc"])
        self._tab_cond(self.g["cond"])
        self._tab_def(self.g["def"])
        self._tab_ana(self.g["ana"])
        self._tab_ser(self.g["ser"])
        self._build_dmap()
        self._build_chart()
        self._build_right()
        B = self.a2dBottomCenter
        self.hint = ui.label(B, 'LMB rotate · RMB pan · wheel zoom · Space fire · Tab panels · C section',
                             (0.0, 0.04), 0.027, DIM, TextNode.ACenter)
        self.bar_bg = DirectFrame(parent=B, frameSize=(-0.6, 0.6, -0.004, 0.004), pos=(0, 0, 0.1), frameColor=LINE, relief=DGG.FLAT)
        self.bar = DirectFrame(parent=B, frameSize=(0, 0.001, -0.004, 0.004), pos=(-0.6, 0, 0.1), frameColor=ACCENT, relief=DGG.FLAT)
        self.time_lbl = ui.label(B, "", (0.0, 0.125), 0.03, FG, TextNode.ACenter)
        self.status = ui.label(self.a2dBottomLeft, "", (LW + 0.03, 0.085), 0.027, DIM)
        self._sync_toggles()
        self._sync_modes()
        self.set_tab("target")

    # ---------------------------------------------------------------- "Target" tab
    def _tab_target(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        self.lst_head = ui.label(g, "", (x0, -0.275), 0.027, DIM)
        self.rows, self.swatches = [], []
        for i in range(ROWS):
            y = -0.335 - i * 0.056
            b = ui.button(g, "", (x0, y), (ww, 0.052), self.on_select, color=BG2, scale=0.031,
                          align=TextNode.ALeft, extra=dict(extraArgs=[i], text_pos=(0.07, -0.031 * 0.3)))
            sw = DirectFrame(parent=b, frameSize=(0.012, 0.045, -0.017, 0.017), frameColor=(0.5, 0.5, 0.5, 1),
                             relief=DGG.FLAT, state=DGG.DISABLED)
            self.rows.append(b)
            self.swatches.append(sw)
        yb = -0.335 - ROWS * 0.056 - 0.002
        names = [('Add', self.add_layer), ('Copy', self.dup_layer), ('Up', lambda: self.move_layer(-1)),
                 ('Down', lambda: self.move_layer(1)), ('Delete', self.del_layer)]
        bw = (ww - 4 * 0.01) / 5
        for i, (n, c) in enumerate(names):
            ui.button(g, n, (x0 + i * (bw + 0.01), yb), (bw, 0.054), c, color=BG3 if i == 0 else BG2, scale=0.028)
        # stack diagram
        ui.label(g, 'STACK DIAGRAM  (along line of fire →)', (x0, yb - 0.065), 0.025, DIM)
        self.strip = ui.group(g)
        self.strip_y = yb - 0.135
        self.strip_info = ui.label(g, "", (x0 + ww, yb - 0.065), 0.025, DIM, TextNode.ARight)
        # editor
        ye = yb - 0.215
        self.page_btns = {
            "layer": ui.button(g, 'Layer', (x0, ye), ((ww - 0.01) / 2, 0.052), self.set_page, scale=0.029, extra=dict(extraArgs=["layer"])),
            "plate": ui.button(g, 'Plate geometry', (x0 + (ww - 0.01) / 2 + 0.01, ye), ((ww - 0.01) / 2, 0.052), self.set_page, scale=0.029,
                               extra=dict(extraArgs=["plate"]))}
        self.pg = {"layer": ui.group(g), "plate": ui.group(g)}
        y = ye - 0.075
        pl = self.pg["layer"]
        self.dd_mat = Dropdown(ui, pl, (x0, y), ww, self._mat_items(), 0, self.on_mat, h=0.056, scale=0.032, per_col=14)
        self.sl_t = SliderRow(ui, pl, (x0, y - 0.065), ww, 'Thickness, mm', 2, 1000, 50, 1, self.on_t)
        self.sl_a = SliderRow(ui, pl, (x0, y - 0.16), ww, 'Angle from normal, deg', 0, 80, 0, 1, self.on_a)
        self.sl_g = SliderRow(ui, pl, (x0, y - 0.255), ww, 'Gap behind layer, mm', 0, 600, 0, 5, self.on_g)
        self.mat_info = ui.label(pl, "", (x0, y - 0.34), 0.025, DIM, wrap=ww / 0.025)
        pp = self.pg["plate"]
        self.dd_shape = Dropdown(ui, pp, (x0, y), ww, [("rect", 'Rectangular plate'), ("round", 'Round plate (diameter = width)')], 0,
                                 self.on_shape, h=0.056, scale=0.032)
        self.sl_w = SliderRow(ui, pp, (x0, y - 0.065), ww, 'Width, mm', 0, 1500, 0, 5, self.on_w, zero_text='auto')
        self.sl_h = SliderRow(ui, pp, (x0, y - 0.16), ww, 'Height, mm', 0, 1500, 0, 5, self.on_h, zero_text='auto')
        self.sl_ou = SliderRow(ui, pp, (x0, y - 0.255), ww, 'Center offset along tilt, mm', -600, 600, 0, 5, self.on_ou)
        self.sl_ov = SliderRow(ui, pp, (x0, y - 0.35), ww, 'Center offset horizontal, mm', -600, 600, 0, 5, self.on_ov)
        self.geo_info = ui.label(pp, "", (x0, y - 0.435), 0.026, DIM, wrap=ww / 0.026)

    # ---------------------------------------------------------------- "Projectile" tab
    def _tab_ammo(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        ui.label(g, 'AMMUNITION', (x0, -0.275), 0.027, DIM)
        items = [(k, AMMO[k].name) for k in AMMO_ORDER]
        self.dd_ammo = Dropdown(ui, g, (x0, -0.335), ww, items, AMMO_ORDER.index(self.ammo_key), self.on_ammo, per_col=12)
        self.ammo_info = ui.label(g, "", (x0, -0.43), 0.027, FG, font=self.mono)
        self.sl_v = SliderRow(ui, g, (x0, -0.78), ww, 'Velocity, m/s', 300, 2000, self.v, 10, self.on_v)
        self.sl_yaw = SliderRow(ui, g, (x0, -0.875), ww, 'Projectile yaw, deg', 0, 8, 0, 0.5, self.on_yaw, "{:.1f}")
        self.sl_so = SliderRow(ui, g, (x0, -0.78), ww, 'Standoff, charge calibers', 0.5, 12, 6, 0.25, self.on_so, "{:.2f}")
        ui.hline(g, x0, LW - 0.04, -0.97)
        ui.label(g, 'WITNESS PLATE (RHA behind target)', (x0, -1.02), 0.027, DIM)
        self.btn_wit = ui.button(g, "", (x0, -1.085), (ww, 0.056), self.toggle_witness, scale=0.03)
        self.sl_wg = SliderRow(ui, g, (x0, -1.16), ww, 'Gap to witness plate, mm', 0, 600, 50, 5, self.on_wg)
        self.btn_cer = ui.button(g, "", (x0, -1.43), (ww, 0.056), self.toggle_cer, scale=0.028)
        self.ammo_note = ui.label(g, 'The witness plate shows how much penetration the projectile has left behind the target.',
                                  (x0, -1.285), 0.025, DIM, wrap=ww / 0.025)

    # ---------------------------------------------------------------- "Materials" tab
    def _tab_mats(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        ui.label(g, 'MATERIAL EDITOR', (x0, -0.275), 0.027, DIM)
        self.dd_med = Dropdown(ui, g, (x0, -0.335), ww, self._mat_items(False), 0, self.on_med_pick, h=0.056, scale=0.032, per_col=14)
        bw = (ww - 2 * 0.01) / 3
        ui.button(g, 'New', (x0, -0.405), (bw, 0.054), self.med_new, scale=0.029, color=BG3)
        ui.button(g, 'Save', (x0 + bw + 0.01, -0.405), (bw, 0.054), self.med_save, scale=0.029, color=BG3)
        ui.button(g, 'Delete', (x0 + 2 * (bw + 0.01), -0.405), (bw, 0.054), self.med_delete, scale=0.029)
        ui.label(g, 'Name', (x0, -0.475), 0.027, DIM)
        self.ent_name = ui.entry(g, (x0, -0.52), ww, "", None, 0.032)
        self.dd_kind = Dropdown(ui, g, (x0, -0.605), ww, [(k, n) for k, n in KINDS], 0, self.on_med_kind, h=0.054, scale=0.031)
        y = -0.68
        self.ms = {}
        specs = [("rho", 'Density, kg/m³', 100, 20000, 7850, 10, "{:.0f}"),
                 ("yield", 'Yield strength, GPa', 0.01, 6.0, 1.0, 0.01, "{:.2f}"),
                 ("rt", 'Rt: resistance for rods and bullets, GPa', 0.02, 25.0, 5.0, 0.02, "{:.2f}"),
                 ("rj", 'Rj: resistance for shaped-charge jet, GPa', 0.3, 35.0, 16.0, 0.1, "{:.1f}"),
                 ("spall", 'Tendency to rear fragment spall', 0.0, 1.0, 0.4, 0.01, "{:.2f}"),
                 ("r", 'Color: red', 0.0, 1.0, 0.5, 0.01, "{:.2f}"),
                 ("gr", 'Color: green', 0.0, 1.0, 0.5, 0.01, "{:.2f}"),
                 ("b", 'Color: blue', 0.0, 1.0, 0.5, 0.01, "{:.2f}")]
        for i, (k, lab, a, b, v, st, fmt) in enumerate(specs):
            self.ms[k] = SliderRow(ui, g, (x0, y - i * 0.093), ww, lab, a, b, v, st, lambda val, kk=k: self.on_med_field(kk, val), fmt)
        self.swatch = DirectFrame(parent=g, frameSize=(0, 0.1, -0.03, 0.03), pos=(x0 + ww - 0.1, 0, y - 5 * 0.093 - 0.28),
                                  frameColor=(0.5, 0.5, 0.5, 1), relief=DGG.FLAT)
        self.med_note = ui.label(g, "", (x0, y - 8 * 0.093 - 0.02), 0.026, DIM, wrap=ww / 0.026)

    # ---------------------------------------------------------------- "Scenes" tab
    def _tab_scenes(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        ui.label(g, 'PRESET EXAMPLES', (x0, -0.275), 0.027, DIM)
        pitems = [(i, n) for i, (n, _) in enumerate(PRESETS)]
        self.dd_pre = Dropdown(ui, g, (x0, -0.335), ww, pitems, 0, self.on_preset, h=0.056, scale=0.03, per_col=14)
        self.dd_pre.btn["text"] = 'Select an example…'
        ui.hline(g, x0, LW - 0.04, -0.395)
        ui.label(g, 'SAVED SCENES  (scenes folder)', (x0, -0.44), 0.027, DIM)
        self.scene_rows = []
        for i in range(7):
            b = ui.button(g, "", (x0, -0.5 - i * 0.054), (ww - 0.15, 0.05), self.on_scene_pick, color=BG2, scale=0.03,
                          align=TextNode.ALeft, extra=dict(extraArgs=[i]))
            self.scene_rows.append(b)
        ui.button(g, 'Up', (x0 + ww - 0.14, -0.5), (0.14, 0.05), self._scene_scroll, scale=0.027, extra=dict(extraArgs=[-3]))
        ui.button(g, 'Down', (x0 + ww - 0.14, -0.5 - 0.054), (0.14, 0.05), self._scene_scroll, scale=0.027, extra=dict(extraArgs=[3]))
        self.scene_cnt = ui.label(g, "", (x0 + ww - 0.14, -0.5 - 2 * 0.054 - 0.01), 0.024, DIM)
        yb = -0.5 - 7 * 0.054 - 0.0
        bw = (ww - 2 * 0.01) / 3
        ui.button(g, 'Load', (x0, yb), (bw, 0.054), self.load_scene, scale=0.029, color=BG3)
        ui.button(g, 'Delete', (x0 + bw + 0.01, yb), (bw, 0.054), self.delete_scene, scale=0.029)
        ui.button(g, 'Refresh', (x0 + 2 * (bw + 0.01), yb), (bw, 0.054), self.refresh_scenes, scale=0.029)
        ui.label(g, 'New scene name', (x0, yb - 0.075), 0.027, DIM)
        self.ent_scene = ui.entry(g, (x0, yb - 0.125), ww, self.scene_name, self._scene_name_enter, 0.032)
        ui.button(g, 'Save scene', (x0, yb - 0.2), ((ww - 0.01) / 2, 0.058), self.save_scene, scale=0.029, color=BG3)
        ui.button(g, 'Clear target', (x0 + (ww - 0.01) / 2 + 0.01, yb - 0.2), ((ww - 0.01) / 2, 0.058), self.clear_scene, scale=0.029)
        self.scene_status = ui.label(g, "", (x0, yb - 0.275), 0.026, DIM, wrap=ww / 0.026)



    # ---------------------------------------------------------------- "Conditions" and "Analysis" tabs
    def _tab_def(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        ui.label(g, 'DEFECTS AND SPECIAL MODES (assumptions, not measurements)', (x0, -0.275), 0.027, DIM)
        self.sl_kw = SliderRow(ui, g, (x0, -0.335), ww, 'Weld seam K_weld (1.00 = no seam)', 0.70, 1.00, 1.00, 0.01, self.on_kw, "{:.2f}")
        self.sl_ks = SliderRow(ui, g, (x0, -0.435), ww, 'Synergy k_syn (0 = from materials)', 0.0, 0.5, 0.0, 0.05, self.on_ks, "{:.2f}")
        self.sl_surf = SliderRow(ui, g, (x0, -0.535), ww, 'Surface cracks, %', 0, 10, 0, 0.5, self.on_surf, "{:.1f}")
        self.sl_pb = SliderRow(ui, g, (x0, -0.635), ww, 'Porosity as channels β (shaped charge only)', 0, 8, 4, 0.5, self.on_pb, "{:.1f}")
        self.sl_sh = SliderRow(ui, g, (x0, -0.735), ww, 'Core self-sharpening, % (0 = none)', 0, 15, 0, 1, self.on_sharp)
        self.btn_hyper = ui.button(g, "", (x0, -0.835), (ww, 0.056), self.toggle_hyper, scale=0.027, color=BG3)
        self._sync_hyper()
        self.sl_tenv = SliderRow(ui, g, (x0, -0.915), ww, 'External heating, °C (with 1D heat transfer)', 20, 2800, 20, 20, self.on_tenv)
        self.sl_hs = SliderRow(ui, g, (x0, -1.015), ww, 'Heating time, s (0 = off)', 0, 600, 0, 10, self.on_hs)
        self.sl_ric = SliderRow(ui, g, (x0, -1.115), ww, 'Ricochet threshold base, ° (default 62)', 40, 75, 62, 1, self.on_ric)
        ui.label(g, 'Hypervelocity (v > 3 km/s, meteoroids): Cour-Palais, vaporized\nfraction, debris cloud (Whipple shield). Thresholds are\nassumptions; details in hyper.py and README.',
                 (x0, -1.215), 0.0245, DIM)

    def on_kw(self, v):
        if v >= 0.995:
            self.cond.pop("k_weld", None)
        else:
            self.cond["k_weld"] = float(v)

    def on_ks(self, v):
        if v <= 0.001:
            self.cond.pop("k_syn", None)
        else:
            self.cond["k_syn"] = float(v)

    def on_surf(self, v):
        if v <= 0:
            self.cond.pop("surf", None)
        else:
            self.cond["surf"] = float(v)

    def on_pb(self, v):
        self.cond["por_beta"] = float(v)

    def on_sharp(self, v):
        if v <= 0:
            self.cond.pop("sharp", None)
        else:
            self.cond["sharp"] = float(v) / 100.0

    def on_ric(self, v):
        if abs(v - 62.0) < 0.5:
            self.cond.pop("ric_base", None)
        else:
            self.cond["ric_base"] = float(v)

    def on_tenv(self, v):
        self.cond["t_env"] = float(v)

    def on_hs(self, v):
        if v <= 0:
            self.cond.pop("heat_s", None)
        else:
            self.cond["heat_s"] = float(v)

    def toggle_hyper(self):
        self.cond["hyper"] = 0 if self.cond.get("hyper", 1) else 1
        self._sync_hyper()

    def _sync_hyper(self):
        try:
            self.btn_hyper["text"] = 'Hypervelocity mode: ' + ('on' if self.cond.get("hyper", 1) else 'off (Tate only)')
        except Exception:
            pass

    def _tab_cond(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        ui.label(g, 'ENVIRONMENT AND MATERIAL CONDITIONS (assumptions)', (x0, -0.275), 0.027, DIM)
        self.sl_temp = SliderRow(ui, g, (x0, -0.335), ww, 'Ambient temperature, °C', -60, 800, 20, 10, self.on_temp)
        self.sl_por = SliderRow(ui, g, (x0, -0.435), ww, 'Porosity after HIP, %', 0, 5, 0, 0.5, self.on_por, "{:.1f}")
        self.sl_cyc = SliderRow(ui, g, (x0, -0.535), ww, 'Load cycles N', 1, 100, 1, 1, self.on_cyc)
        self.sl_pre = SliderRow(ui, g, (x0, -0.635), ww, 'Thermal shock: preheat to, °C (before impact)', -70, 800, -70, 10, self.on_pre,
                                zero_text='off')
        ui.hline(g, x0, LW - 0.04, -0.715)
        ui.label(g, 'MULTIPLE HITS', (x0, -0.76), 0.027, DIM)
        bw = (ww - 0.01) / 2
        ui.button(g, 'Second shot at the same point', (x0, -0.825), (bw, 0.056), self.second_shot, scale=0.026, color=BG3)
        ui.button(g, 'Reset damage', (x0 + bw + 0.01, -0.825), (bw, 0.056), self.reset_damage, scale=0.026)
        self.cond_info = ui.label(g, "", (x0, -0.90), 0.0245, FG, font=self.mono)
        ui.hline(g, x0, LW - 0.04, -1.095)
        ui.label(g, 'ACOUSTIC LAYER INTERFACES (Z = ρ·c)', (x0, -1.14), 0.027, DIM)
        self.imp_info = ui.label(g, "", (x0, -1.195), 0.0245, FG, font=self.mono)

    def _tab_ana(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        ui.label(g, 'CHARTS AND EXPORT', (x0, -0.275), 0.027, DIM)
        bw = (ww - 0.01) / 2
        self.btn_chart = ui.button(g, "", (x0, -0.34), (bw, 0.056), self.toggle_chart, scale=0.027)
        ui.button(g, 'Next chart', (x0 + bw + 0.01, -0.34), (bw, 0.056), self.next_chart, scale=0.027)
        ui.button(g, 'Export CSV + JSON (reports folder)', (x0, -0.41), (ww, 0.056), self.export_results, scale=0.027)
        ui.hline(g, x0, LW - 0.04, -0.475)
        ui.label(g, 'MONTE CARLO AND V50', (x0, -0.52), 0.027, DIM)
        self.sl_mcn = SliderRow(ui, g, (x0, -0.575), ww, 'Runs per point', 20, 200, 60, 20, lambda v: self.mc_cfg.update(n=int(v)))
        self.sl_mcr = SliderRow(ui, g, (x0, -0.675), ww, 'Density scatter ±σ, %', 0, 15, 5, 1, lambda v: self.mc_cfg.update(s_rho=v))
        self.sl_mcs = SliderRow(ui, g, (x0, -0.775), ww, 'Strength scatter ±σ, %', 0, 30, 10, 1, lambda v: self.mc_cfg.update(s_str=v))
        ui.button(g, 'Run Monte Carlo / V50', (x0, -0.885), (ww, 0.056), self.run_mc, scale=0.028, color=BG3)
        self.mc_info = ui.label(g, 'Velocity v50 is computed for kinetic rounds; the run uses NORMAL mode.', (x0, -0.955), 0.0245, DIM,
                                font=self.mono)
        self._sync_chart_btn()


    # ---------------------------------------------------------------- "Series" tab
    def _tab_ser(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        c = self.ser_cfg
        ui.label(g, 'HIT SERIES (dispersion, 2D damage field D, cracks)', (x0, -0.275), 0.027, DIM)
        self.sl_sn = SliderRow(ui, g, (x0, -0.33), ww, 'Number of hits', 1, 60, c["n"], 1, lambda v: c.update(n=int(v)))
        self.sl_ss = SliderRow(ui, g, (x0, -0.43), ww, 'Dispersion σ over area, mm', 0, 300, c["sigma"], 5, lambda v: c.update(sigma=float(v)),
                               zero_text='single point')
        self.sl_sk = SliderRow(ui, g, (x0, -0.53), ww, 'Crack transfer between layers, %', 0, 200, 100 * c["k"], 5,
                               lambda v: c.update(k=float(v) / 100.0))
        self.sl_sr = SliderRow(ui, g, (x0, -0.63), ww, 'Series for statistics', 1, 30, c["runs"], 1, lambda v: c.update(runs=int(v)))
        bw = (ww - 0.01) / 2
        ui.button(g, 'Fire series', (x0, -0.735), (ww, 0.058), self.run_series, scale=0.029, color=BG3)
        self.btn_dmap = ui.button(g, "", (x0, -0.81), (bw, 0.054), self.toggle_dmap, scale=0.027)
        self.btn_dlay = ui.button(g, "", (x0 + bw + 0.01, -0.81), (bw, 0.054), self.next_dmap_layer, scale=0.027)
        ui.button(g, 'Export series (CSV, D grids)', (x0, -0.88), (ww, 0.054), self.export_series, scale=0.027)
        self.ser_info = ui.label(g, 'The series fires the current projectile at the current stack\n'
                                    '(NORMAL mode). Penetration depends on D at the hit point;\n'
                                    'dispersion may send the projectile past the plate.',
                                 (x0, -0.95), 0.0245, DIM, font=self.mono)
        self._sync_dmap_btn()

    def run_series(self):
        if any(e["focus"] for e in self.ui.entries):
            return
        c = self.ser_cfg
        a = AMMO[self.ammo_key]
        kw = dict(cond=dict(self.cond), mode="NORMAL", yaw=self.yaw, standoff=self.standoff_m(), witness=self.witness,
                  witness_gap=self.witness_gap, k_crack=c["k"])
        t0 = time.time()
        try:
            self.ser = SR.run_series(self.ammo_key, self.v, self.layers, c["n"], c["sigma"] / 1000.0, **kw)
            self.ser_stats = None
            if c["sigma"] > 0 and c["runs"] > 1:
                self.ser_stats = SR.series_stats(self.ammo_key, self.v, self.layers, c["n"], c["sigma"] / 1000.0, runs=c["runs"], **kw)
        except Exception as e:
            traceback.print_exc()
            self._status('Series error: %s' % e)
            return
        self.dmap_layer = min(self.dmap_layer, len(self.layers) - 1)
        L = SR.series_lines(self.ser, self.ser_stats)
        self.ser_info.setText("\n".join(L[:16]))
        self.dmap_on = True
        self.dmap.show()
        self._sync_dmap_btn()
        self._draw_dmap()
        self._status('Series: %d hits in %.1f s' % (c["n"], time.time() - t0))

    def export_series(self):
        if not self.ser:
            self._status('Fire a series first')
            return
        try:
            files = SR.export_series(os.path.join(ROOT, "reports"), self.ser)
            self._status('Series export: %d files → reports' % len(files))
        except Exception as e:
            traceback.print_exc()
            self._status('Export error: %s' % e)

    def _sync_dmap_btn(self):
        self.btn_dmap["text"] = 'D map: ' + ('hide' if self.dmap_on else 'show')
        n = len(self.ser.layers) if self.ser else len(self.layers)
        self.btn_dlay["text"] = 'Map layer: %d / %d' % (min(self.dmap_layer, max(n - 1, 0)) + 1, max(n, 1))

    def toggle_dmap(self):
        self.dmap_on = not self.dmap_on
        self._sync_dmap_btn()
        if self.dmap_on:
            self.dmap.show()
            self._draw_dmap()
        else:
            self.dmap.hide()

    def next_dmap_layer(self):
        n = len(self.ser.layers) if self.ser else len(self.layers)
        self.dmap_layer = (self.dmap_layer + 1) % max(n, 1)
        self._sync_dmap_btn()
        if self.dmap_on:
            self._draw_dmap()

    def _build_dmap(self):
        self.dmap = DirectFrame(parent=self.aspect2d, frameSize=(-0.64, 0.64, -0.47, 0.47), pos=(-0.02, 0, 0.03),
                                frameColor=(0.04, 0.05, 0.065, 1.0), relief=DGG.FLAT)
        self.dmap.hide()
        self._dmap_img = None

    def _dmap_txt(self, text, x, y, scale=0.022, fg=FG, align=TextNode.ALeft):
        t = self.ui.label(self.dmap, text, (x, y), scale, fg, align)
        self.dmap_nodes.append(t)
        return t

    def _draw_dmap(self):
        from panda3d.core import PNMImage, Texture, SamplerState
        for n in self.dmap_nodes:
            try:
                n.removeNode() if hasattr(n, "removeNode") else n.destroy()
            except Exception:
                pass
        self.dmap_nodes = []
        s = self.ser
        if s is None:
            self._dmap_txt('Damage map D', -0.60, 0.40, 0.03, ACCENT)
            self._dmap_txt('Press "Fire series".', -0.30, 0.0, 0.026, DIM)
            return
        i = min(self.dmap_layer, len(s.layers) - 1)
        G = s.field.G[i]
        N = G.shape[0]
        img = PNMImage(N, N, 3)
        stops = [(0.0, (0.07, 0.09, 0.13)), (0.15, (0.15, 0.25, 0.42)), (0.5, (0.95, 0.60, 0.12)), (0.8, (0.90, 0.20, 0.10)), (1.0, (1.0, 0.95, 0.85))]

        def col(v):
            for (a0, c0), (a1, c1) in zip(stops, stops[1:]):
                if v <= a1:
                    f = (v - a0) / (a1 - a0) if a1 > a0 else 0.0
                    return tuple(c0[k] + f * (c1[k] - c0[k]) for k in range(3))
            return stops[-1][1]
        for r in range(N):
            for c in range(N):
                img.setXel(c, r, *col(float(G[N - 1 - r, c])))
        tex = Texture("dmap")
        tex.load(img)
        tex.setMagfilter(SamplerState.FT_linear)
        tex.setMinfilter(SamplerState.FT_linear)
        self._dmap_tex = tex
        fr = DirectFrame(parent=self.dmap, frameSize=(-0.42, 0.42, -0.42, 0.42), pos=(-0.17, 0, -0.01), frameTexture=tex, relief=DGG.FLAT)
        self.dmap_nodes.append(fr)
        k = 0.42 / SR.GRID_R          # screen units per meter
        cx, cy = -0.17, -0.01
        l = s.layers[i]
        self._dmap_txt('Damage field D · layer %d (%s) · field ±%.0f mm' % (i + 1, l.mat.split("~")[0], 1000 * SR.GRID_R), -0.62, 0.43, 0.026, ACCENT)
        for n_, h in enumerate(s.hits[:60]):
            col_ = RED if h["perf"] else (DIM if h["miss"] else GREEN)
            self._dmap_txt("+", cx + h["x"] * k, cy + h["y"] * k - 0.011, 0.03, col_, TextNode.ACenter)
            self._dmap_txt("%d" % h["n"], cx + h["x"] * k + 0.012, cy + h["y"] * k + 0.002, 0.017, FG)
        # legend
        for j in range(11):
            v = j / 10.0
            c3 = col(v)
            b = DirectFrame(parent=self.dmap, frameSize=(0, 0.05, 0, 0.032), pos=(0.38, 0, -0.38 + j * 0.034), frameColor=(*c3, 1), relief=DGG.FLAT)
            self.dmap_nodes.append(b)
            if j % 5 == 0:
                self._dmap_txt("D=%.1f" % v, 0.44, -0.375 + j * 0.034, 0.02, DIM)
        self._dmap_txt('+ green: stopped', 0.30, 0.30, 0.019, GREEN)
        self._dmap_txt('+ red: penetration', 0.30, 0.27, 0.019, RED)
        self._dmap_txt('+ gray: missed plate', 0.30, 0.24, 0.019, DIM)
        st = s.stats[i]
        self._dmap_txt('mean D %.2f   peak %.2f' % (st["mean"], st["peak"]), 0.30, 0.15, 0.019, FG)
        self._dmap_txt("S(D>0.5) %.0f%%" % (100 * st["area50"]), 0.30, 0.12, 0.019, FG)

    def _sync_cond_sliders(self):
        try:
            self.sl_temp.set(self.cond["temp"]); self.sl_por.set(100 * self.cond["por"]); self.sl_cyc.set(self.cond["cycles"]); self.sl_pre.set(self.cond.get("t_pre", -70.0))
            self.sl_kw.set(self.cond.get("k_weld", 1.0)); self.sl_ks.set(self.cond.get("k_syn", 0.0)); self.sl_surf.set(self.cond.get("surf", 0.0))
            self.sl_pb.set(self.cond.get("por_beta", 4.0)); self.sl_sh.set(100 * self.cond.get("sharp", 0.0)); self._sync_hyper()
            self.sl_tenv.set(self.cond.get("t_env", 20.0)); self.sl_hs.set(self.cond.get("heat_s", 0.0)); self.sl_ric.set(self.cond.get("ric_base", 62.0))
        except Exception:
            pass

    def on_temp(self, v):
        self.cond["temp"] = float(v)

    def on_por(self, v):
        self.cond["por"] = float(v) / 100.0

    def on_cyc(self, v):
        self.cond["cycles"] = float(max(1, v))

    def on_pre(self, v):
        if v <= -69.0:
            self.cond.pop("t_pre", None)
        else:
            self.cond["t_pre"] = float(v)

    def _sync_cond_info(self):
        if not hasattr(self, "cond_info"):
            return
        dm = [l.dmg for l in self.layers]
        t = ['Hits at point: %d' % self.shots]
        t.append('Layer damage (0 = intact, 1 = destroyed):')
        t.append("  " + ("  ".join("%d:%.2f" % (i + 1, d) for i, d in enumerate(dm)) if dm else "—"))
        if self.result is not None and self.result.damage:
            t.append('After the last shot:')
            t.append("  " + "  ".join("%d:%.2f" % (i + 1, d) for i, d in enumerate(self.result.damage)))
        t.append('"Second shot" carries damage into the layers')
        t.append('and fires again: layer strength × (1 - D).')
        self.cond_info.setText("\n".join(t))
        rows = SV.interface_report(self.layers, self.cond.get("temp", 20.0))
        out = []
        for i, a1, b1, tp in rows:
            out.append("%2d %-6s→%-6s Tp=%.2f%s" % (i + 1, a1[:6], b1[:6], tp, '  decoupling' if tp < 0.3 else ""))
        if not out:
            out = ['at least 2 layers needed']
        self.imp_info.setText("\n".join(out[:12] + ['Tp<0.3 — the wave is mostly reflected;',
                                                  'does not affect penetration, informational only.']))

    def second_shot(self):
        if any(e["focus"] for e in self.ui.entries):
            return
        if self.result is None or not self.result.damage:
            self._status('Make the first shot first')
            return
        for l, d, dt in zip(self.layers, self.result.damage, self.result.dth or [0.0] * len(self.layers)):
            l.dmg = float(d)
            l.dth = float(dt)
        if self.cond.pop("t_pre", None) is not None:  # thermal shock is already included in D
            self.sl_pre.set(-70.0)
        self.shots += 1
        self.fire()
        self._status('Shot #%d at damaged armor' % (self.shots + 1))

    def reset_damage(self):
        for l in self.layers:
            l.dmg = 0.0
            l.dth = 0.0
        self.shots = 0
        self._sync_cond_info()
        self._status('Damage reset')

    # ---- Monte Carlo
    def run_mc(self):
        a = AMMO[self.ammo_key]
        self.mc = AN.MonteCarlo(self.ammo_key, self.v, self.layers, n=int(self.mc_cfg["n"]), s_rho=self.mc_cfg["s_rho"] / 100.0,
                                s_str=self.mc_cfg["s_str"] / 100.0, yaw=self.yaw, standoff=self.standoff_m(),
                                witness=self.witness, witness_gap=self.witness_gap, cond=dict(self.cond))
        self.task_mgr.remove("mc")
        self.task_mgr.add(self._mc_task, "mc")

    def _mc_task(self, task):
        m = self.mc
        if m is None:
            return task.done
        try:
            m.step(6)
        except Exception:
            traceback.print_exc()
            self.mc_info.setText('Monte Carlo error')
            self.mc = None
            return task.done
        txt = []
        for ln in m.lines():
            txt += textwrap.wrap(ln, 58) or [""]
        self.mc_info.setText("\n".join(txt))
        return task.done if m.done else task.cont

    # ---- charts
    def _build_chart(self):
        self.chart = DirectFrame(parent=self.aspect2d, frameSize=(-0.64, 0.64, -0.47, 0.47), pos=(-0.02, 0, 0.03),
                                 frameColor=(0.04, 0.05, 0.065, 1.0), relief=DGG.FLAT)
        self.chart.hide()

    def _sync_chart_btn(self):
        self.btn_chart["text"] = 'Chart: ' + ('hide' if self.chart_on else 'show')

    def toggle_chart(self):
        self.chart_on = not self.chart_on
        if self.chart_on:
            self.chart.show()
            self._draw_chart()
        else:
            self.chart.hide()
        self._sync_chart_btn()

    def next_chart(self):
        self.chart_idx = (self.chart_idx + 1) % 4
        if not self.chart_on:
            self.chart_on = True
            self.chart.show()
            self._sync_chart_btn()
        self._draw_chart()

    def _clear_chart(self):
        for n in self.chart_nodes:
            try:
                n.removeNode() if hasattr(n, "removeNode") else n.destroy()
            except Exception:
                pass
        self.chart_nodes = []

    def _txt(self, text, x, y, scale=0.024, fg=FG, align=TextNode.ALeft):
        t = self.ui.label(self.chart, text, (x, y), scale, fg, align)
        self.chart_nodes.append(t)
        return t

    def _line(self, pts, color=(1, 0.64, 0.18, 1), th=2.5):
        from panda3d.core import LineSegs
        ls = LineSegs()
        ls.setThickness(th)
        ls.setColor(*color)
        first = True
        for x, y in pts:
            (ls.moveTo if first else ls.drawTo)(x, 0, y)
            first = False
        n = self.chart.attachNewNode(ls.create())
        self.chart_nodes.append(n)

    def _axes(self, title, xl, yl, x0, x1, y0, y1, xlab=True):
        PX0, PX1, PY0, PY1 = -0.50, 0.58, -0.32, 0.30
        self._txt(title, -0.60, 0.40, 0.03, ACCENT)
        self._line([(PX0, PY0), (PX1, PY0), (PX1, PY1), (PX0, PY1), (PX0, PY0)], LINE, 1.5)
        if x1 <= x0:
            x1 = x0 + 1.0
        if y1 <= y0:
            y1 = y0 + 1.0
        for k in range(6):
            fx = k / 5.0
            xv = x0 + fx * (x1 - x0)
            self._line([(PX0 + fx * (PX1 - PX0), PY0), (PX0 + fx * (PX1 - PX0), PY1)], (0.12, 0.15, 0.18, 1), 1)
            self._txt("%.0f" % xv if abs(x1 - x0) > 8 else "%.2f" % xv, PX0 + fx * (PX1 - PX0), PY0 - 0.035, 0.02, DIM, TextNode.ACenter)
            yv = y0 + fx * (y1 - y0)
            self._line([(PX0, PY0 + fx * (PY1 - PY0)), (PX1, PY0 + fx * (PY1 - PY0))], (0.12, 0.15, 0.18, 1), 1)
            self._txt("%.0f" % yv if abs(y1 - y0) > 8 else "%.2f" % yv, PX0 - 0.012, PY0 + fx * (PY1 - PY0) - 0.006, 0.02, DIM, TextNode.ARight)
        self._txt(xl, 0.04, -0.40, 0.024, DIM, TextNode.ACenter)
        self._txt(yl, -0.60, 0.33, 0.022, DIM)
        mx = lambda x: PX0 + (x - x0) / (x1 - x0) * (PX1 - PX0)
        my = lambda y: PY0 + (y - y0) / (y1 - y0) * (PY1 - PY0)
        return mx, my

    def _draw_chart(self):
        self._clear_chart()
        res = self.result
        names = ['Velocity vs depth', 'Energy by layer', 'Mass efficiency vs mass', 'Coherence / length vs path']
        if res is None:
            self._txt(names[self.chart_idx], -0.60, 0.40, 0.03, ACCENT)
            self._txt('Fire a shot — the chart is built from its result.', -0.5, 0.0, 0.026, DIM)
            return
        rows = self._group_rows(res)
        try:
            if self.chart_idx == 0:
                s, v = AN.chart_data(res, self.layers, rows)["v_depth"]
                n = min(len(s), len(v))
                s, v = s[:n], v[:n]
                if n < 2:
                    self._txt('no data', -0.2, 0.0)
                    return
                mx, my = self._axes(names[0] + " (%s)" % ('jet tip' if res.cls == "heat" else 'projectile nose'),
                                    'depth along shot, mm', 'velocity, m/s', float(s.min()), float(s.max()), 0.0, float(v.max()) * 1.05)
                for sd in res.slab_defs:
                    xx = sd.s_front * 1000.0
                    if s.min() <= xx <= s.max():
                        self._line([(mx(xx), -0.32), (mx(xx), 0.30)], (0.30, 0.42, 0.50, 1), 1)
                self._line([(mx(a), my(b)) for a, b in zip(s, v)])
            elif self.chart_idx == 1:
                en = AN.chart_data(res, self.layers, rows)["energy"]
                if not en or max(e for _, e in en) <= 0:
                    self._txt(names[1], -0.60, 0.40, 0.03, ACCENT)
                    self._txt('per-layer energy is computed in ADVANCED/ULTRA modes', -0.55, 0.0, 0.025, DIM)
                    return
                emax = max(e for _, e in en) * 1.1
                mx, my = self._axes(names[1], 'layer', 'energy, kJ', 0, len(en), 0, emax)
                w = 0.9 * 1.08 / len(en) * 0.7
                for i, (nm, e) in enumerate(en):
                    xc = mx(i + 0.5)
                    fr = DirectFrame(parent=self.chart, frameSize=(-w / 2, w / 2, 0, my(e) - my(0)), pos=(xc, 0, my(0)),
                                     frameColor=ACCENT, relief=DGG.FLAT)
                    self.chart_nodes.append(fr)
                    self._txt(nm[:6], xc, -0.36, 0.019, FG, TextNode.ACenter)
                    self._txt("%.0f" % e, xc, my(e) + 0.01, 0.019, FG, TextNode.ACenter)
            elif self.chart_idx == 2:
                if self.mass_cache is None:
                    self.mass_cache = AN.mass_sweep(self.ammo_key, self.v, self.layers, "NORMAL", self.yaw, self.standoff_m(),
                                                    self.witness, self.witness_gap, self.cond)
                pts = self.mass_cache
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                mx, my = self._axes(names[2] + ' (thickness scale 0.4–2.0)', 'target mass, kg/m²', 'RHA mass / target mass',
                                    min(xs), max(xs), 0.0, max(ys) * 1.15)
                self._line([(mx(a), my(b)) for a, b, _ in pts])
                for a, b, perf in pts:
                    self._txt("[x]" if perf else "[ ]", mx(a), my(b) - 0.008, 0.026, RED if perf else GREEN, TextNode.ACenter)
                self._txt('[x] penetrated   [ ] stopped (value is a lower bound)', -0.5, -0.43, 0.02, DIM)
            else:
                kind, data = AN.chart_data(res, self.layers, rows)["aux"]
                if kind == "heat":
                    pts = data
                    if not pts:
                        self._txt('no data', -0.2, 0.0)
                        return
                    xe = max(res.stack_end * 1000.0, max(p[0] for p in pts) + 10)
                    mx, my = self._axes('Jet coherence vs path', 'layer position along shot, mm', 'coherence (1 = intact)',
                                        0, xe, 0.0, 1.05)
                    path = []
                    for i, (x, c) in enumerate(pts):
                        path += [(mx(x), my(c))]
                        if i + 1 < len(pts):
                            path += [(mx(pts[i + 1][0]), my(c))]
                    path += [(mx(xe), my(pts[-1][1]))]
                    self._line(path)
                else:
                    s, Lr = data
                    n = min(len(s), len(Lr))
                    if n < 2:
                        self._txt('no data', -0.2, 0.0)
                        return
                    mx, my = self._axes('Residual rod length vs path', 'depth along shot, mm', 'length, mm',
                                        float(s[:n].min()), float(s[:n].max()), 0.0, float(Lr[:n].max()) * 1.05)
                    self._line([(mx(a), my(b)) for a, b in zip(s[:n], Lr[:n])])
        except Exception:
            traceback.print_exc()
            self._txt('chart build error', -0.3, 0.0, 0.026, RED)

    def export_results(self):
        if not self.result:
            self._status('Fire a shot first')
            return
        try:
            rows = self._group_rows(self.result)
            files = AN.export_all(os.path.join(ROOT, "reports"), self.result, self.layers, rows,
                                  "\n".join(self.report_lines(self.result)),
                                  extra=(self.mc.result if self.mc and self.mc.done else None))
            self._status('Export: ' + ", ".join(os.path.basename(f) for f in files) + "  → reports")
        except Exception as e:
            traceback.print_exc()
            self._status('Export error: %s' % e)

    # ---------------------------------------------------------------- "Calcs" tab
    def _tab_calc(self, g):
        ui, x0, ww = self.ui, self.x0, self.ww
        ui.label(g, 'ENGINEERING FORMULAS (all 17)', (x0, -0.275), 0.027, DIM)
        items = [(c.key, c.title) for c in C.CALCS]
        self.calc_key = C.CALCS[2].key
        self.dd_calc = Dropdown(ui, g, (x0, -0.335), ww, items, [k for k, _ in items].index(self.calc_key),
                                self.calc_pick, h=0.056, scale=0.029, per_col=12)
        self.cg, self.cent = {}, {}
        for c in C.CALCS:
            grp = ui.group(g)
            self.cg[c.key] = grp
            ents = {}
            y = -0.425
            for f in c.fields:
                if f.text:
                    ui.label(grp, f.label, (x0, y), 0.0235, DIM, wrap=ww / 0.0235)
                    e = ui.entry(grp, (x0, y - 0.048), ww, f.default, lambda t: self.calc_run(), 0.027)
                    y -= 0.105
                else:
                    ui.label(grp, f.label, (x0, y), 0.0235, DIM)
                    e = ui.entry(grp, (x0 + ww - 0.26, y + 0.001), 0.26, f.default, lambda t: self.calc_run(), 0.028)
                    y -= 0.056
                ents[f.key] = e
            self.cent[c.key] = ents
        self.calc_run_btn = ui.button(g, 'Calculate', (x0, -1.19), ((ww - 0.01) / 2, 0.058), self.calc_run, scale=0.029, color=BG3)
        ui.button(g, 'Take from target', (x0 + (ww - 0.01) / 2 + 0.01, -1.19), ((ww - 0.01) / 2, 0.058), self.calc_prefill, scale=0.029)
        self.calc_out = ui.label(g, "", (x0, -1.31), 0.0225, FG, font=self.mono)
        self.calc_pick(self.calc_key)

    def calc_pick(self, key):
        self.calc_key = key
        for k, grp in self.cg.items():
            (grp.show if k == key else grp.hide)()
        self.ui.blur_all()
        self.calc_run()

    def calc_values(self):
        return {k: e.get() for k, e in self.cent[self.calc_key].items()}

    def calc_run(self):
        lines = C.run(self.calc_key, self.calc_values())
        self.calc_out.setText("\n".join(lines))

    def calc_prefill(self):
        a = AMMO[self.ammo_key]
        lay = self._cur() if self.layers else None
        m = MATERIALS[lay.mat] if lay and lay.mat in MATERIALS else MATERIALS["RHA"]
        ents = self.cent[self.calc_key]
        FE = {"RHA": "Fe", "MILD": "Fe", "HHS": "Fe", "AL5083": "Al", "AL7039": "Al", "TI64": "Ti"}
        CORE_H = {"W": "W", "DU": "U", "STEEL": "Fe"}

        def put(k, val):
            if k in ents:
                ents[k].enterText(str(val))
        scale = 0.45 if a.cls == "ap" else 1.0
        if a.cls != "heat":
            core = CORES[a.core]
            mass_g = rod_mass(a) * 1000
            if self.calc_key == "tate":
                put("L", "%g" % a.L_mm); put("v", "%g" % self.v); put("rp", "%g" % core.rho); put("rt", "%g" % m.rho)
                put("Yp", "%g" % core.yield_gpa); put("Rt", "%.3g" % (m.rt_gpa * scale))
            elif self.calc_key == "demarre":
                put("d", "%g" % a.d_mm); put("m", "%.4g" % mass_g); put("v", "%g" % self.v)
                put("al", "%g" % (lay.angle if lay else 0)); put("h", "%g" % (lay.t * 1000 if lay else 25))
            elif self.calc_key == "energy":
                put("m", "%.4g" % mass_g); put("v", "%g" % self.v)
            elif self.calc_key == "pressure":
                put("mp", CORE_H.get(a.core, "Fe")); put("mt", FE.get(m.key, "Fe")); put("v", "%g" % self.v)
        else:
            if self.calc_key == "jet":
                put("rj", "%g" % D.CU_RHO); put("rt", "%g" % m.rho)
        if m.k_stoy and self.calc_key == "demarre":
            put("K", "%g" % m.k_stoy)
        if self.calc_key == "strength":
            put("sy", "%g" % (m.yield_gpa * 1000))
            if m.k_weld:
                put("Kw", "%g" % m.k_weld)
        if self.calc_key == "thermal" and m.tm_c:
            put("el", ""); put("c", "%g" % m.c_jkgk); put("Tm", "%g" % m.tm_c)
        if self.calc_key == "mass" and lay:
            put("rho", "%g" % m.rho); put("h", "%g" % (lay.t * 1000))
        self.calc_run()
        self._status('Values taken from the current target (layer %d, %s)' % (self.sel + 1, m.key) if lay else
                     'Values taken from the current projectile')

    # ---------------------------------------------------------------- right panel
    def _build_right(self):
        ui = self.ui
        r = self.right
        xr = -RW + 0.04
        rw = RW - 0.08
        ui.label(r, 'SOLVER', (xr, -0.07), 0.027, DIM)
        self.mode_btns = {}
        bw3 = (rw - 2 * 0.012) / 3
        for i, m in enumerate(MODES):
            self.mode_btns[m] = ui.button(r, m, (xr + i * (bw3 + 0.012), -0.13), (bw3, 0.062), self.set_mode, color=BG2, scale=0.032,
                                          extra=dict(extraArgs=[m]))
        self.mode_help = ui.label(r, MODE_HELP[self.mode], (xr, -0.2), 0.026, DIM, wrap=rw / 0.026)
        self.btn_fire = ui.button(r, 'FIRE   [Space]', (xr, -0.295), (rw, 0.092), self.fire, color=(0.85, 0.50, 0.08, 1),
                                  fg=(0.05, 0.04, 0.02, 1), scale=0.044)
        bw4 = (rw - 3 * 0.012) / 4
        ui.button(r, 'Pause', (xr, -0.385), (bw4, 0.056), self.toggle_pause, scale=0.029)
        ui.button(r, 'Reset', (xr + (bw4 + 0.012), -0.385), (bw4, 0.056), self.reset, scale=0.029)
        ui.button(r, 'Frame', (xr + 2 * (bw4 + 0.012), -0.385), (bw4, 0.056), self.frame_cam, scale=0.029)
        ui.button(r, 'View', (xr + 3 * (bw4 + 0.012), -0.385), (bw4, 0.056), self.cycle_view, scale=0.029)
        self.sl_ts = SliderRow(ui, r, (xr, -0.455), rw, 'Clip duration (slow motion), s', 3, 30, 9, 0.5, self.on_ts, "{:.1f}")
        self.btn_sec = ui.button(r, "", (xr, -0.565), ((rw - 0.012) / 2, 0.056), self.toggle_section, scale=0.029)
        self.btn_lab = ui.button(r, "", (xr + (rw - 0.012) / 2 + 0.012, -0.565), ((rw - 0.012) / 2, 0.056), self.toggle_labels, scale=0.029)
        ui.hline(r, xr, -0.04, -0.625)
        self.res_head = ui.label(r, 'Press "FIRE"', (xr, -0.695), 0.05, DIM)
        ui.button(r, 'Report .txt', (-0.04 - 0.24, -0.675), (0.24, 0.05), self.save_report, scale=0.027)
        self.res_text = ui.label(r, "", (xr, -0.755), 0.0245, FG, font=self.mono)

    # ================================================================== synchronization
    def _mat_items(self, with_era=True):
        items = [(k, mat_name(k)) for k in MATERIAL_ORDER if k != ERA_KEY]
        if with_era:
            items.append((ERA_KEY, ERA_NAME))
        return items

    def set_tab(self, k):
        self.tab = k
        for kk, g in self.g.items():
            (g.show if kk == k else g.hide)()
        for kk, b in self.tab_btns.items():
            c = (0.78, 0.46, 0.08, 1) if kk == k else BG2
            b["frameColor"] = (c, shade(c, 1.4), shade(c, 1.25), shade(c, 0.7))
            b["text_fg"] = (0.05, 0.04, 0.02, 1) if kk == k else FG
        self.ui.blur_all()
        if k == "mats":
            self._med_load(self.mat_edit_key)
        if k == "scenes":
            self.refresh_scenes()
        if k == "ammo":
            self._sync_ammo_ui()
        if k == "cond":
            self._sync_cond_info()
        if k == "target":
            self.set_page(self.edit_page)

    def set_page(self, p):
        self.edit_page = p
        for k, g in self.pg.items():
            (g.show if k == p else g.hide)()
        for k, b in self.page_btns.items():
            c = (0.10, 0.20, 0.22, 1) if k == p else BG2
            b["frameColor"] = (c, shade(c, 1.5), shade(c, 1.3), c)
            b["text_fg"] = TEAL if k == p else FG

    def _sync_toggles(self):
        self.btn_sec["text"] = 'Section: ' + ('on' if self.section else 'off')
        self.btn_lab["text"] = 'Labels: ' + ('on' if self.labels else 'off')
        self.btn_cer["text"] = 'Ceramic effect on jet (coherence): ' + ('on' if SV.JET_CERAMIC_EFFECT else 'off')
        self.btn_wit["text"] = 'Witness plate: ' + ('on' if self.witness else 'off')

    def _sync_modes(self):
        for m, b in self.mode_btns.items():
            c = (0.78, 0.46, 0.08, 1) if m == self.mode else BG2
            b["frameColor"] = (c, shade(c, 1.4), shade(c, 1.25), shade(c, 0.7))
            b["text_fg"] = (0.05, 0.04, 0.02, 1) if m == self.mode else FG
        self.mode_help.setText(MODE_HELP[self.mode])

    def _dc(self):
        a = AMMO[self.ammo_key]
        return (a.d_mm / 1000.0) if a.cls != "heat" else 0.35 * a.d_mm / 1000.0

    def _sync_ammo_ui(self):
        a = AMMO[self.ammo_key]
        heat = a.cls == "heat"
        if heat:
            self.sl_v.hide(); self.sl_yaw.hide(); self.sl_so.show()
            self.sl_so.set(self.standoff_cd)
        else:
            self.sl_v.show(); self.sl_yaw.show(); self.sl_so.hide()
            self.sl_v.set(self.v); self.sl_yaw.set(self.yaw)
        self.sl_wg.set(self.witness_gap * 1000)
        self.ammo_info.setText(self._ammo_text())

    def _ammo_text(self):
        a = AMMO[self.ammo_key]
        L = [a.name, 'country: ' + a.nation, ""]
        if a.cls == "heat":
            L += ['Shaped charge %.0f mm' % a.d_mm, 'jet head %d m/s' % a.vt, 'jet tail   %d m/s' % a.vmin,
                  'optimal standoff ≈ %.0f mm' % (a.s_opt_cd * a.d_mm), 'claimed ~%d mm RHA' % a.rated_mm]
        else:
            c = CORES[a.core]
            L += ['Core: ' + c.name, 'd = %.1f mm, L = %.0f mm (L/D = %.0f)' % (a.d_mm, a.L_mm, a.L_mm / a.d_mm),
                  'core mass %.2f kg' % rod_mass(a), 'energy %.0f kJ' % (0.5 * rod_mass(a) * self.v ** 2 / 1000),
                  'nose: ' + ('pointed' if a.nose == "pointed" else 'blunt')]
        L.append('data: ' + a.src)
        return "\n".join(L)

    def _layer_text(self, i, l):
        g = plate_geom(l, self._dc())
        nm = 'ERA' if l.mat == ERA_KEY else (l.mat if not MATERIALS[l.mat].user else MATERIALS[l.mat].name[:9])
        tail = '  miss' if not g["hit"] else ""
        return '%d  %s  %d mm  @%d°%s' % (i + 1, nm, round(l.t * 1000), round(l.angle), tail)

    def _sync_layers_ui(self):
        n = len(self.layers)
        self.list_off = max(0, min(self.list_off, max(0, n - ROWS)))
        if self.sel < self.list_off:
            self.list_off = self.sel
        if self.sel >= self.list_off + ROWS:
            self.list_off = self.sel - ROWS + 1
        for slot, b in enumerate(self.rows):
            i = self.list_off + slot
            if i < n:
                l = self.layers[i]
                b["text"] = self._layer_text(i, l)
                c = (0.10, 0.20, 0.22, 1) if i == self.sel else BG2
                b["frameColor"] = (c, shade(c, 1.5), shade(c, 1.3), c)
                b["text_fg"] = TEAL if i == self.sel else FG
                self.swatches[slot]["frameColor"] = mat_color(l.mat)
                b.show()
            else:
                b.hide()
        if n:
            self.lst_head.setText('LAYERS %d–%d of %d  ·  mouse wheel over list scrolls' % (self.list_off + 1, min(n, self.list_off + ROWS), n))
        else:
            self.lst_head.setText('NO LAYERS — press "Add"')
        self._draw_strip()

    def _sync_editor(self):
        if not self.layers:
            return
        self.sel = max(0, min(self.sel, len(self.layers) - 1))
        l = self.layers[self.sel]
        self.dd_mat.set_items(self._mat_items(), self.dd_mat.key_index(l.mat))
        self.sl_t.set(l.t * 1000); self.sl_a.set(l.angle); self.sl_g.set(l.gap * 1000)
        self.dd_shape.set_index(0 if l.shape == "rect" else 1)
        self.sl_w.set(l.w * 1000); self.sl_h.set(l.h * 1000); self.sl_ou.set(l.ou * 1000); self.sl_ov.set(l.ov * 1000)
        if l.mat == ERA_KEY:
            self.mat_info.setText('Reactive armor: two flyer plates and a charge. Works against a jet, weaker against a rod. '
                                  'Model parameters: assumption.')
        else:
            m = MATERIALS[l.mat]
            self.mat_info.setText('ρ = %d kg/m³ · Rt = %.1f GPa · Rj = %.1f GPa · data: %s%s' % (
                m.rho, m.rt_gpa, m.rj_gpa, m.src, (" · " + m.note) if m.note else ""))
        self._geo_info()

    def _geo_info(self):
        if not self.layers:
            return
        l = self.layers[self.sel]
        g = plate_geom(l, self._dc())
        if l.shape == "round":
            sz = 'diameter %.0f mm' % (g["W"] * 1000)
        else:
            sz = '%.0f × %.0f mm (w × h)' % (g["W"] * 1000, g["Hh"] * 1000)
        auto = ' · size auto' if (l.w <= 0 and (l.h <= 0 or l.shape == "round")) else ""
        if g["hit"]:
            self.geo_info.setText('The shot hits the plate. ' + sz + auto)
            self.geo_info["fg"] = GREEN
        else:
            self.geo_info.setText('The shot passes this plate by (it is off the line of fire). ' + sz + auto)
            self.geo_info["fg"] = RED

    def _draw_strip(self):
        for c in self.strip.getChildren():
            c.removeNode()
        ui, x0, ww, y = self.ui, self.x0, self.ww, self.strip_y
        n = len(self.layers)
        DirectFrame(parent=self.strip, frameSize=(x0, x0 + ww, -0.04, 0.04), pos=(0, 0, y), frameColor=(0.04, 0.05, 0.065, 1), relief=DGG.FLAT)
        if not n:
            return
        dc = self._dc()
        Ts, gaps = [], []
        for l in self.layers:
            c = max(math.cos(l.angle * math.pi / 180), 0.2)
            Ts.append(l.t / c); gaps.append(l.gap)
        total = sum(Ts) + sum(gaps[:-1]) if n > 1 else Ts[0]
        total = max(total * 1.08, 0.02)
        sc = (ww - 0.04) / total
        x = x0 + 0.02
        # line of fire
        DirectFrame(parent=self.strip, frameSize=(x0, x0 + ww, -0.0015, 0.0015), pos=(0, 0, y), frameColor=(0.2, 0.55, 0.6, 1), relief=DGG.FLAT)
        pos_s = []
        for i, l in enumerate(self.layers):
            wbar = max(Ts[i] * sc, 0.006)
            g = plate_geom(l, dc)
            col = mat_color(l.mat)
            if not g["hit"]:
                col = (col[0] * 0.45, col[1] * 0.45, col[2] * 0.45, 1)
            if i == self.sel:
                DirectFrame(parent=self.strip, frameSize=(x - 0.004, x + wbar + 0.004, -0.04, 0.04), pos=(0, 0, y), frameColor=TEAL, relief=DGG.FLAT)
            h = 0.03 if g["hit"] else 0.018
            DirectFrame(parent=self.strip, frameSize=(x, x + wbar, -h, h), pos=(0, 0, y), frameColor=col, relief=DGG.FLAT)
            pos_s.append((x, wbar))
            x += wbar + (gaps[i] * sc if i < n - 1 else 0)
        res = self.result
        if res is not None and res.slab_defs:
            s_end = 0.0
            for sl, sr in zip(res.slab_defs, res.slabs):
                if sl.role != "witness" and sr.depth > 0:
                    s_end = max(s_end, sl.s_front + sr.depth)
            xm = x0 + 0.02 + s_end * sc
            colv = {'PENETRATED': RED, 'STOPPED': GREEN, 'RICOCHET': BLUE}[res.verdict]
            if xm < x0 + ww:
                DirectFrame(parent=self.strip, frameSize=(xm - 0.002, xm + 0.002, -0.04, 0.04), pos=(0, 0, y), frameColor=colv, relief=DGG.FLAT)
        tot_mm = (sum(Ts) + sum(gaps[:-1])) * 1000 if n > 1 else Ts[0] * 1000
        self.strip_info.setText('path along line of fire %.0f mm' % tot_mm)

    # ================================================================== bindings
    def _bind(self):
        self.accept("space", self.fire)
        self.accept("p", self.toggle_pause)
        self.accept("r", self.reset)
        self.accept("c", self.toggle_section)
        self.accept("f", self.frame_cam)
        self.accept("l", self.toggle_labels)
        self.accept("tab", self.toggle_panels)
        self.accept("delete", self.del_layer)
        self.accept("control-s", self.save_scene)
        for i, m in enumerate(MODES):
            self.accept(str(i + 1), self.set_mode, [m])
        self.accept("mouse1", self._md, [1]); self.accept("mouse1-up", self._mu)
        self.accept("mouse3", self._md, [3]); self.accept("mouse3-up", self._mu)
        self.accept("mouse2", self._md, [3]); self.accept("mouse2-up", self._mu)
        self.accept("wheel_up", self._wheel, [-1]); self.accept("wheel_down", self._wheel, [1])
        self.accept("arrow_left", self._nudge, [-5, 0]); self.accept("arrow_right", self._nudge, [5, 0])
        self.accept("arrow_up", self._nudge, [0, 4]); self.accept("arrow_down", self._nudge, [0, -4])
        self.accept("escape", self.user_exit)

    def _md(self, btn):
        self.ui.blur_all()
        if self.mouseWatcherNode.is_over_region():
            self._drag = None
            return
        if self.mouseWatcherNode.has_mouse():
            m = self.mouseWatcherNode.get_mouse()
            self._drag = (btn, m.x, m.y)

    def _mu(self):
        self._drag = None

    def _mouse_a2d(self):
        if not self.mouseWatcherNode.has_mouse():
            return None
        m = self.mouseWatcherNode.get_mouse()
        return m.x * self.getAspectRatio(), m.y

    def _wheel(self, d):
        if self.mouseWatcherNode.is_over_region():
            pos = self._mouse_a2d()
            if pos:
                x, y = pos
                ar = self.getAspectRatio()
                if -ar < x < -ar + LW:
                    if self.tab == "target" and 1 - 0.30 > y > 1 - 0.80:
                        self.list_off = max(0, min(max(0, len(self.layers) - ROWS), self.list_off + d))
                        self._sync_layers_ui()
                    elif self.tab == "scenes" and 1 - 0.46 > y > 1 - 0.90:
                        self.scene_off = max(0, min(max(0, len(self.scene_files) - 7), self.scene_off + d))
                        self._sync_scene_rows()
            return
        w = self.world
        w.cam_dist = max(0.12, min(12.0, w.cam_dist * (1.0 + 0.1 * d)))
        w.apply_camera()

    def _nudge(self, daz, de):
        if any(e["focus"] for e in self.ui.entries):
            return
        w = self.world
        w.cam_az += daz; w.cam_el = max(-85, min(85, w.cam_el + de)); w.apply_camera()

    def _cam_drag(self):
        if not self._drag or not self.mouseWatcherNode.has_mouse():
            return
        btn, x0, y0 = self._drag
        m = self.mouseWatcherNode.get_mouse()
        dx, dy = m.x - x0, m.y - y0
        w = self.world
        if btn == 1:
            w.cam_az -= dx * 130
            w.cam_el = max(-85, min(85, w.cam_el - dy * 90))
        else:
            k = w.cam_dist * 0.9
            az = math.radians(w.cam_az)
            right = (math.cos(az), math.sin(az), 0)
            w.cam_target.x -= right[0] * dx * k
            w.cam_target.y -= right[1] * dx * k
            w.cam_target.z -= dy * k * 0.6
        w.apply_camera()
        self._drag = (btn, m.x, m.y)

    # ================================================================== handlers
    def on_ammo(self, key):
        self.ammo_key = key
        a = AMMO[key]
        self.v = a.v
        if a.cls == "heat":
            self.standoff_cd = a.s_opt_cd
        self._sync_ammo_ui(); self._sync_layers_ui(); self._geo_info()
        self._changed(True)

    def on_v(self, v):
        self.v = v; self.ammo_info.setText(self._ammo_text()); self._changed()

    def on_yaw(self, v):
        self.yaw = v; self._changed()

    def on_so(self, v):
        self.standoff_cd = v; self._changed()

    def on_wg(self, v):
        self.witness_gap = v / 1000.0; self._changed()

    def on_select(self, slot):
        i = self.list_off + slot
        if i < len(self.layers):
            self.sel = i
            self._sync_layers_ui(); self._sync_editor()

    def _cur(self):
        return self.layers[self.sel] if self.layers else None

    def _edited(self, rebuild_now=False):
        self._sync_layers_ui(); self._geo_info(); self._changed(rebuild_now)

    def on_mat(self, key):
        l = self._cur()
        if l:
            l.mat = key
            self._sync_layers_ui(); self._sync_editor(); self._changed(True)

    def on_t(self, v):
        l = self._cur()
        if l:
            l.t = v / 1000.0; self._edited()

    def on_a(self, v):
        l = self._cur()
        if l:
            l.angle = v; self._edited()

    def on_g(self, v):
        l = self._cur()
        if l:
            l.gap = v / 1000.0; self._edited()

    def on_shape(self, k):
        l = self._cur()
        if l:
            l.shape = k; self._edited(True)

    def on_w(self, v):
        l = self._cur()
        if l:
            l.w = v / 1000.0; self._edited()

    def on_h(self, v):
        l = self._cur()
        if l:
            l.h = v / 1000.0; self._edited()

    def on_ou(self, v):
        l = self._cur()
        if l:
            l.ou = v / 1000.0; self._edited()

    def on_ov(self, v):
        l = self._cur()
        if l:
            l.ov = v / 1000.0; self._edited()

    def on_ts(self, v):
        self.duration = v

    def on_preset(self, i):
        if isinstance(i, int) and 0 <= i < len(PRESETS):
            self.load_preset(i)

    def set_mode(self, m):
        self.mode = m
        self._sync_modes()
        self._changed()

    def toggle_section(self):
        self.section = not self.section
        self._sync_toggles(); self._changed(True)

    def toggle_labels(self):
        self.labels = not self.labels
        self._sync_toggles(); self._changed(True)

    def toggle_cer(self):
        SV.JET_CERAMIC_EFFECT = not SV.JET_CERAMIC_EFFECT
        self._sync_toggles()
        self._changed(True)

    def toggle_witness(self):
        self.witness = not self.witness
        self._sync_toggles(); self._changed(True)

    def toggle_pause(self):
        if self.playing:
            self.paused = not self.paused

    def toggle_panels(self):
        self._panels = not getattr(self, "_panels", True)
        for pnl in (self.left, self.right):
            (pnl.show if self._panels else pnl.hide)()

    def frame_cam(self):
        self._frame_i = 1 - getattr(self, "_frame_i", 1)
        if self._frame_i:
            self.world.frame_camera()
        else:
            self.world.frame_impact()

    def cycle_view(self):
        w = self.world
        views = [(0.0, 0.0), (-24.0, 14.0), (-60.0, 20.0), (0.0, 78.0)]
        cur = (getattr(self, "_view_i", 0) + 1) % len(views)
        self._view_i = cur
        w.cam_az, w.cam_el = views[cur]
        w.apply_camera()

    # ---- layers
    def add_layer(self):
        if len(self.layers) >= MAX_LAYERS:
            self._status('Limit reached: %d layers' % MAX_LAYERS)
            return
        self.layers.append(Layer("RHA", 0.050, 0.0, 0.0))
        self.sel = len(self.layers) - 1
        self._sync_layers_ui(); self._sync_editor(); self._changed(True)

    def dup_layer(self):
        if len(self.layers) >= MAX_LAYERS or not self.layers:
            return
        l = self.layers[self.sel]
        self.layers.insert(self.sel + 1, Layer(l.mat, l.t, l.angle, l.gap, l.w, l.h, l.shape, l.ou, l.ov))
        self.sel += 1
        self._sync_layers_ui(); self._sync_editor(); self._changed(True)

    def del_layer(self):
        if not self.layers or any(e["focus"] for e in self.ui.entries):
            return
        del self.layers[self.sel]
        self.sel = max(0, min(self.sel, len(self.layers) - 1))
        self._sync_layers_ui(); self._sync_editor(); self._changed(True)

    def move_layer(self, d):
        j = self.sel + d
        if 0 <= j < len(self.layers):
            self.layers[self.sel], self.layers[j] = self.layers[j], self.layers[self.sel]
            self.sel = j
            self._sync_layers_ui(); self._changed(True)

    def clear_scene(self):
        self.layers = []
        self.sel = 0
        self._sync_layers_ui(); self._changed(True)
        self._scene_msg('Target cleared')

    # ---- presets
    def load_preset(self, i):
        name, p = PRESETS[i]
        self.ammo_key = p["ammo"]
        a = AMMO[self.ammo_key]
        self.v = a.v
        self.yaw = 0.0
        self.standoff_cd = p.get("standoff_cd", a.s_opt_cd)
        self.layers = [Layer(l.mat, l.t, l.angle, l.gap, l.w, l.h, l.shape, l.ou, l.ov) for l in p["layers"]]
        self.mode = p.get("mode", "ULTRA")
        self.sel = 0
        self.list_off = 0
        self.dd_ammo.set_index(AMMO_ORDER.index(self.ammo_key))
        self._sync_ammo_ui(); self._sync_layers_ui(); self._sync_editor(); self._sync_modes()
        self._changed(True, frame=True)

    # ================================================================== materials
    def _refresh_material_lists(self):
        self.dd_mat.set_items(self._mat_items(), self.dd_mat.key_index(self._cur().mat if self.layers else "RHA"))
        self.dd_med.set_items(self._mat_items(False), self.dd_med.key_index(self.mat_edit_key))

    def _med_load(self, key):
        if key not in MATERIALS:
            key = "RHA"
        self.mat_edit_key = key
        m = MATERIALS[key]
        self._med = dict(name=m.name, rho=m.rho, yield_=m.yield_gpa, rt=m.rt_gpa, rj=m.rj_gpa, kind=m.kind,
                         spall=m.spall, color=list(m.color))
        self.dd_med.set_items(self._mat_items(False), self.dd_med.key_index(key))
        self.ent_name.enterText(m.name)
        self.dd_kind.set_index([k for k, _ in KINDS].index(m.kind) if m.kind in dict(KINDS) else 0)
        for k, v in (("rho", m.rho), ("yield", m.yield_gpa), ("rt", m.rt_gpa), ("rj", m.rj_gpa), ("spall", m.spall),
                     ("r", m.color[0]), ("gr", m.color[1]), ("b", m.color[2])):
            self.ms[k].set(v)
        self.swatch["frameColor"] = tuple(m.color) + (1,)
        if m.user:
            self.med_note.setText('Custom material. "Save" will update it, file materials_user.json.')
        else:
            self.med_note.setText('Built-in material, read-only (data: %s). "Save" will create a copy with a new name.' % m.src)

    def on_med_pick(self, key):
        self._med_load(key)

    def on_med_kind(self, k):
        self._med["kind"] = k

    def on_med_field(self, k, v):
        if "color" not in self._med:
            return
        if k in ("r", "gr", "b"):
            idx = {"r": 0, "gr": 1, "b": 2}[k]
            self._med["color"][idx] = v
            self.swatch["frameColor"] = tuple(self._med["color"]) + (1,)
        elif k == "yield":
            self._med["yield_"] = v
        else:
            self._med[k] = v

    def med_new(self):
        base = MATERIALS[self.mat_edit_key]
        self._med_save_as(base, 'New material')

    def med_save(self):
        name = (self.ent_name.get() or "").strip() or 'Material'
        base = MATERIALS[self.mat_edit_key]
        if base.user:
            m = self._build_material(base.key, name)
            D.register_material(m)
            self._med_after('Material "%s" saved' % name)
        else:
            if name == base.name:
                name += ' (copy)'
            self._med_save_as(base, name)

    def _build_material(self, key, name):
        md = self._med
        return Material(key, name, float(md["rho"]), float(md["yield_"]), float(md["rt"]), float(md["rj"]), md["kind"],
                        tuple(round(c, 3) for c in md["color"]), float(md["spall"]), "user", "", True)

    def _med_save_as(self, base, name):
        key = D.new_user_key(name)
        if name == 'New material':
            self._med = dict(name=name, rho=base.rho, yield_=base.yield_gpa, rt=base.rt_gpa, rj=base.rj_gpa,
                             kind=base.kind, spall=base.spall, color=list(base.color))
        m = self._build_material(key, name)
        D.register_material(m)
        self.mat_edit_key = key
        self._med_after('Material "%s" created' % name)

    def _med_after(self, msg):
        try:
            D.save_user_materials(USER_MATS)
        except Exception as e:
            msg += ' (could not write file: %s)' % e
        self._refresh_material_lists()
        self._med_load(self.mat_edit_key)
        self._sync_layers_ui(); self._sync_editor()
        self.med_note.setText(msg)
        self._changed(True)

    def med_delete(self):
        key = self.mat_edit_key
        m = MATERIALS.get(key)
        if not m or not m.user:
            self.med_note.setText('Built-in materials cannot be deleted.')
            return
        for l in self.layers:
            if l.mat == key:
                l.mat = "RHA"
        D.delete_user_material(key)
        self.mat_edit_key = "RHA"
        self._med_after('Material deleted, its layers switched to RHA')

    # ================================================================== 3D scene
    def _changed(self, now=False, frame=False):
        if self._rebuild_job is not None:
            self.task_mgr.remove(self._rebuild_job)
            self._rebuild_job = None
        if now:
            self._rebuild(frame)
        else:
            self._rebuild_job = self.task_mgr.do_method_later(0.12, self._rebuild_task, "rebuild")
        self.playing = False

    def _rebuild_task(self, task):
        self._rebuild_job = None
        self._rebuild(False)
        return task.done

    def standoff_m(self):
        a = AMMO[self.ammo_key]
        return self.standoff_cd * a.d_mm / 1000.0 if a.cls == "heat" else 0.0

    def _rebuild(self, frame=False):
        self.result = None
        self.playing = False
        self.world.build(self.ammo_key, self.layers, self.yaw, self.standoff_m(), self.witness, self.witness_gap, self.section, self.labels)
        if frame:
            self.world.frame_camera()
        self.res_head.setText('Press "FIRE"'); self.res_head["fg"] = DIM
        self.res_text.setText(self._setup_text())
        self.bar["frameSize"] = (0, 0.001, -0.004, 0.004)
        self.time_lbl.setText("")
        self._draw_strip()

    def _setup_text(self):
        a = AMMO[self.ammo_key]
        lines = [a.name, ""]
        areal = sum((MATERIALS[l.mat].rho if l.mat in MATERIALS else 3500.0) * l.t for l in self.layers)
        lines.append('Layers: %d' % len(self.layers))
        lines.append('Areal density: %.0f kg/m²' % areal)
        if a.cls == "heat":
            lines.append('Standoff %.0f mm (optimum ≈ %.0f mm)' % (self.standoff_m() * 1000, a.s_opt_cd * a.d_mm))
        else:
            lines.append('Projectile energy %.0f kJ' % (0.5 * rod_mass(a) * self.v ** 2 / 1000))
        miss = [i + 1 for i, l in enumerate(self.layers) if not plate_geom(l, self._dc())["hit"]]
        if miss:
            lines.append('Off line of fire: layers ' + ", ".join(map(str, miss)))
        return "\n".join(lines)

    # ================================================================== shot
    def fire(self):
        if any(e["focus"] for e in self.ui.entries):
            return
        try:
            res = solve(self.ammo_key, self.v, self.layers, self.mode, yaw=self.yaw,
                        standoff=self.standoff_m(), witness=self.witness, witness_gap=self.witness_gap,
                        cond=self.cond)
        except Exception:
            traceback.print_exc()
            self.res_head.setText('Calculation error'); self.res_head["fg"] = RED
            self.res_text.setText(traceback.format_exc()[-400:])
            return
        self.result = res
        self.world.build(self.ammo_key, self.layers, self.yaw, self.standoff_m(), self.witness, self.witness_gap, self.section, self.labels)
        self.world.load_result(res)
        self.wall_t = 0.0
        self.playing = True
        self.paused = False
        self.mass_cache = None
        self._show_result(res)
        self._draw_strip()
        self._sync_cond_info()
        if self.chart_on:
            self._draw_chart()

    def reset(self):
        if any(e["focus"] for e in self.ui.entries):
            return
        self._rebuild(False)

    def _tick(self, task):
        self._cam_drag()
        dt = min(globalClock.get_dt(), 0.1)
        if self.playing and self.result is not None:
            if not self.paused:
                self.wall_t += dt
            f = min(self.wall_t / self.duration, 1.0)
            t0, t1 = self.world.t_total
            t = t0 + (t1 - t0) * f
            self.world.set_time(t)
            self.bar["frameSize"] = (0, max(1.2 * f, 0.001), -0.004, 0.004)
            self.time_lbl.setText('t = %+.0f µs' % (t * 1e6))
            if f >= 1.0:
                self.playing = False
                self.world.set_time(t1 + 1e-6)
        return task.cont

    # ================================================================== report

    def _show_result(self, res):
        col = {'PENETRATED': RED, 'STOPPED': GREEN, 'RICOCHET': BLUE}.get(res.verdict, FG)
        self.res_head.setText(res.verdict)
        self.res_head["fg"] = col
        self.res_text.setText("\n".join(self.report_lines(res)))

    def save_report(self):
        if not self.result:
            self._status('Fire a shot first')
            return
        d = os.path.join(ROOT, "reports"); os.makedirs(d, exist_ok=True)
        fn = os.path.join(d, "report_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
        with open(fn, "w", encoding="utf-8") as f:
            f.write('ARMORLAB 3D\nVerdict: %s\n' % self.result.verdict)
            f.write("\n".join(self.report_lines(self.result)))
        self._status('Report saved: ' + fn)

    # ================================================================== scenes
    def _status(self, msg):
        self.status.setText(msg)

    def _scene_msg(self, msg):
        self.scene_status.setText(msg)
        self._status(msg)

    def _scene_dict(self):
        used = {l.mat for l in self.layers}
        mats = [D.material_to_dict(MATERIALS[k]) for k in sorted(used) if k in MATERIALS and MATERIALS[k].user]
        return dict(version=2, ammo=self.ammo_key, v=self.v, yaw=self.yaw, standoff_cd=self.standoff_cd,
                    mode=self.mode, witness=self.witness, witness_gap=self.witness_gap, cond=dict(self.cond), series=dict(self.ser_cfg),
                    layers=[dict(mat=l.mat, t=l.t, angle=l.angle, gap=l.gap, w=l.w, h=l.h, shape=l.shape,
                                 ou=l.ou, ov=l.ov, dmg=l.dmg, dth=l.dth) for l in self.layers],
                    materials=mats)

    def refresh_scenes(self):
        try:
            os.makedirs(SCENES, exist_ok=True)
            self.scene_files = sorted(f for f in os.listdir(SCENES) if f.lower().endswith(".json"))
        except Exception:
            self.scene_files = []
        if self.scene_sel >= len(self.scene_files):
            self.scene_sel = -1
        self.scene_off = max(0, min(max(0, len(self.scene_files) - 7), self.scene_off))
        self._sync_scene_rows()

    def _scene_scroll(self, d):
        self.scene_off = max(0, min(max(0, len(self.scene_files) - 7), self.scene_off + d))
        self._sync_scene_rows()

    def _sync_scene_rows(self):
        try:
            n = len(self.scene_files)
            self.scene_cnt["text"] = '%d-%d of %d' % (min(n, self.scene_off + 1), min(n, self.scene_off + 7), n)
        except Exception:
            pass
        for i, b in enumerate(self.scene_rows):
            j = self.scene_off + i
            if j < len(self.scene_files):
                b["text"] = "  " + self.scene_files[j][:-5]
                b["frameColor"] = BG3 if j == self.scene_sel else BG2
            else:
                b["text"] = ""
                b["frameColor"] = BG2

    def on_scene_pick(self, i):
        j = self.scene_off + i
        if j < len(self.scene_files):
            self.scene_sel = j
            name = self.scene_files[j][:-5]
            self.scene_name = name
            self.ent_scene.enterText(name)
            self._sync_scene_rows()

    def _scene_name_enter(self, txt):
        self.scene_name = txt.strip() or self.scene_name

    def save_scene(self):
        name = re.sub(r'[\\/:*?"<>|]+', "_", (self.ent_scene.get() or self.scene_name).strip())[:48] or 'scene'
        self.scene_name = name
        try:
            os.makedirs(SCENES, exist_ok=True)
            fn = os.path.join(SCENES, name + ".json")
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(self._scene_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._scene_msg('Could not save: %s' % e)
            return
        self.refresh_scenes()
        if name + ".json" in self.scene_files:
            self.scene_sel = self.scene_files.index(name + ".json")
            self._sync_scene_rows()
        self._scene_msg('Saved: scenes/%s.json' % name)

    def load_scene(self):
        if not (0 <= self.scene_sel < len(self.scene_files)):
            self._scene_msg('Select a scene in the list')
            return
        fn = os.path.join(SCENES, self.scene_files[self.scene_sel])
        try:
            with open(fn, encoding="utf-8") as f:
                d = json.load(f)
            for md in d.get("materials", []):
                if md["key"] not in MATERIALS:
                    D.register_material(D.material_from_dict(md))
            ammo = d.get("ammo", "M829A1")
            if ammo not in AMMO:
                ammo = "M829A1"
            layers = []
            for l in d.get("layers", [])[:MAX_LAYERS]:
                mat = l.get("mat", "RHA")
                if mat not in MATERIALS:
                    mat = "RHA"
                layers.append(Layer(mat, float(l.get("t", 0.05)), float(l.get("angle", 0.0)), float(l.get("gap", 0.0)),
                                    float(l.get("w", 0.0)), float(l.get("h", 0.0)), l.get("shape", "rect"),
                                    float(l.get("ou", 0.0)), float(l.get("ov", 0.0)), float(l.get("dmg", 0.0)), float(l.get("dth", 0.0))))
        except Exception as e:
            self._scene_msg('Read error: %s' % e)
            return
        self.ammo_key = ammo
        a = AMMO[ammo]
        self.v = float(d.get("v", a.v))
        self.yaw = float(d.get("yaw", 0.0))
        self.standoff_cd = float(d.get("standoff_cd", a.s_opt_cd))
        self.witness = bool(d.get("witness", True))
        self.witness_gap = float(d.get("witness_gap", 0.05))
        self.mode = d.get("mode", "ULTRA") if d.get("mode") in MODES else "ULTRA"
        self.layers = layers
        c = d.get("cond", {}) or {}
        self.cond = dict(temp=float(c.get("temp", 20.0)), por=float(c.get("por", 0.0)), cycles=float(c.get("cycles", 1.0)))
        if c.get("t_pre") is not None:
            self.cond["t_pre"] = float(c["t_pre"])
        for _k in ("k_weld", "k_syn", "surf", "por_beta", "sharp", "hyper", "t_env", "heat_s", "ric_base"):
            if c.get(_k) is not None:
                self.cond[_k] = float(c[_k])
        self._sync_cond_sliders()
        sc = d.get("series") or {}
        self.ser_cfg.update({k: sc[k] for k in ("n", "sigma", "k", "runs") if k in sc})
        self.ser = None
        self.ser_stats = None
        self.sl_sn.set(self.ser_cfg["n"]); self.sl_ss.set(self.ser_cfg["sigma"]); self.sl_sk.set(100 * self.ser_cfg["k"]); self.sl_sr.set(self.ser_cfg["runs"])
        self.sel = 0
        self.list_off = 0
        self.dd_ammo.set_index(AMMO_ORDER.index(ammo))
        self._refresh_material_lists()
        self._sync_ammo_ui(); self._sync_layers_ui(); self._sync_editor(); self._sync_modes(); self._sync_toggles()
        self._changed(True, frame=True)
        self._scene_msg('Loaded: %s' % self.scene_files[self.scene_sel][:-5])

    def delete_scene(self):
        if not (0 <= self.scene_sel < len(self.scene_files)):
            self._scene_msg('Select a scene in the list')
            return
        fn = self.scene_files[self.scene_sel]
        try:
            os.remove(os.path.join(SCENES, fn))
        except Exception as e:
            self._scene_msg('Could not delete: %s' % e)
            return
        self.scene_sel = -1
        self.refresh_scenes()
        self._scene_msg('Deleted: %s' % fn[:-5])

    def _group_rows(self, res):
        rows = []
        i = 0
        slabs = res.slabs
        while i < len(slabs):
            s = slabs[i]
            if s.role == "flyer":
                s2 = slabs[i + 1]
                rows.append(dict(parent=s.parent, name='ERA', T=s.T + s2.T, depth=s.depth + s2.depth, perf=s.perforated and s2.perforated,
                                 v_in=s.v_in, v_out=s2.v_out, mode='triggered' if s.era_active else 'not triggered',
                                 notes=s.notes + s2.notes, e=s.e_abs + s2.e_abs, angle=s.angle, witness=False, sp_n=0, sp_v=0.0, sp_m=0.0, sp_rv=-1.0, sp_rm=0.0))
                i += 2
                continue
            rows.append(dict(parent=s.parent, name='wit.' if s.role == "witness" else s.mat, T=s.T, depth=s.depth,
                             perf=s.perforated, v_in=s.v_in, v_out=s.v_out, mode=s.mode, notes=s.notes, e=s.e_abs,
                             angle=s.angle, witness=s.role == "witness", sp_n=s.spall_n, sp_v=s.spall_v,
                             sp_m=s.spall_mass, sp_rv=s.spall_rv, sp_rm=s.spall_rm))
            i += 1
        return rows

    def report_lines(self, res):
        a = AMMO[res.ammo]
        L = []
        L.append('%s · solver %s · %.0f ms' % (a.name, res.mode, res.solve_ms))
        if res.cls == "heat":
            L.append('standoff %.0f mm' % (res.standoff * 1000))
        else:
            L.append('v0 = %.0f m/s, E0 = %.0f kJ' % (self.v, res.e0 / 1000))
        L.append("")
        L.append('reference: free RHA 0° ........ %5.0f mm' % (res.free_depth * 1000))
        if res.verdict == 'PENETRATED':
            L.append('absorbed (RHA-eq.) ............. %5.0f mm' % (res.rhae * 1000))
        elif res.verdict == 'STOPPED':
            L.append('absorbed (RHA-eq.) ............. ≥%4.0f mm' % (res.free_depth * 1000))
        areal = sum((MATERIALS[l.mat].rho if l.mat in MATERIALS else 3500.0) * l.t for l in self.layers)
        if areal > 0:
            rh = res.rhae if res.verdict == 'PENETRATED' else res.free_depth
            ge = "" if res.verdict == 'PENETRATED' else "≥"
            tsum = sum(l.t for l in self.layers)
            rha_m = rh * 7850.0
            L.append('target mass .................... %5.0f kg/m²' % areal)
            L.append('RHA of equal resistance ........ %s%4.0f mm = %.0f kg/m²' % (ge, rh * 1000, rha_m))
            dm = (areal / rha_m - 1.0) * 100 if rha_m > 0 else 0
            L.append('vs steel: %s by %.0f%%' % ('heavier' if dm > 0 else 'lighter', abs(dm)))
            L.append('mass efficiency ................. %s%.2f' % (ge, rha_m / areal))
            L.append('thickness efficiency ............ %s%.2f' % (ge, rh / tsum if tsum > 0 else 0))
        if res.verdict == 'PENETRATED':
            if res.cls != "heat" and res.L_res > 0.002:
                L.append('residual: v = %.0f m/s, L = %.0f mm' % (res.v_res, res.L_res * 1000))
            if self.witness:
                L.append('behind target (wit. RHA) ....... %5.0f mm%s' % (res.witness_depth * 1000, "+" if res.witness_through else ""))
        L.append("")
        L.append('layer    @   LOS  path   v in→out  result')
        for r in self._group_rows(res):
            if r["mode"] == 'missed plate':
                st = 'miss'
            elif r["depth"] <= 0 and not r["perf"]:
                st = 'not reached' if r["v_in"] == 0 else "—"
            else:
                st = 'through' if r["perf"] else 'stop'
            vin = "%4.0f" % r["v_in"] if r["v_in"] else "   -"
            vout = "%4.0f" % r["v_out"] if (r["v_out"] and r["perf"]) else "   -"
            L.append("%-6s %3.0f° %4.0f %5.0f  %s→%s  %s" % (r["name"], r["angle"], r["T"] * 1000, r["depth"] * 1000, vin, vout, st))
            if not r["perf"] and r["v_out"] and r["depth"] > 0 and res.cls != "heat":
                L.append('   · projectile consumed, fragment v≈%.0f m/s' % r["v_out"])
            if r["mode"]:
                L.append("   · " + r["mode"])
            for n in r["notes"]:
                L.append("   · " + n)
            if res.mode != "NORMAL" and r["e"] > 0:
                L.append('   · layer energy %.0f kJ' % (r["e"] / 1000))
            if r["sp_n"] and r["sp_m"] > 0 and not r["witness"]:
                L.append('   · rear spall: ~%d fragments, v≈%.0f m/s, m≈%.0f g' % (r["sp_n"], r["sp_v"], r["sp_m"] * 1000))
        eb = res.jet.get("e_bal") if res.cls == "heat" else None
        if eb and eb["init"] > 0:
            k = 1e-3
            L.append("")
            L.append('jet energy balance (kJ): total %.0f' % (eb["init"] * k))
            L.append('   absorbed by layers %.0f · jet breakup %.0f · coherence loss %.0f' % (
                eb["slabs"] * k, eb["breakup"] * k, eb["coh"] * k))
            L.append('   element stopping %.0f · exited armor %.0f · other/residual %.0f (%.1f%%)' % (
                eb["stop"] * k, eb["exit"] * k, eb["other"] * k, 100.0 * eb["other"] / eb["init"]))
        rows_all = [r for r in self._group_rows(res) if not r["witness"] and r["mode"] != 'missed plate']
        src = [r for r in rows_all if r["sp_n"] and r["sp_m"] > 0]
        if src:
            lined = [r for r in src if r["sp_rv"] >= 0 and r["sp_rv"] < r["sp_v"] + 1e-6 and any(
                'absorbs spall fragments' in n for q in rows_all for n in q["notes"])]
            left = [r for r in src if r["sp_rv"] < 0 or r["sp_rv"] > 5.0]
            L.append("")
            if not left:
                L.append('behind-armor effect (estimate): spall fragments')
                L.append('stopped by layers behind the armor, do not leave the target')
            else:
                b = max(left, key=lambda r: (r["sp_rv"] if r["sp_rv"] >= 0 else r["sp_v"]) * (r["sp_rm"] if r["sp_rv"] >= 0 else r["sp_m"]) ** 0.5)
                rv = b["sp_rv"] if b["sp_rv"] >= 0 else b["sp_v"]
                rm = b["sp_rm"] if b["sp_rv"] >= 0 else b["sp_m"]
                L.append('behind-armor effect (estimate): behind the last layer')
                L.append('fragments up to %.0f m/s, mass ≈ %.0f g (layer %s)' % (rv, rm * 1000, b["name"]))
                if lined:
                    L.append('spall liner partly stopped the flow')
        c = res.cond or {}
        if c and (abs(c.get("temp", 20.0) - 20.0) > 1e-6 or c.get("por", 0.0) > 0 or c.get("cycles", 1.0) > 1):
            L.append("")
            L.append('conditions: T=%.0f°C, porosity %.1f%%, cycles N=%.0f' % (c.get("temp", 20.0), 100 * c.get("por", 0.0), c.get("cycles", 1.0)))
        for w_ in getattr(res, "warns", []):
            L.append("! " + w_)
        if res.pre:
            L.append("")
            L.append('tandem: precursor (%s) — %s' % (res.pre["name"], res.pre["verdict"].lower()))
            hit = ['%s %.0f mm' % (m, d * 1000) for m, d, T, pf in res.pre["depths"] if d > 0]
            if hit:
                L.append('   penetrated layers: ' + ", ".join(hit))
            L.append('   damage D from precursor: ' + " ".join("%d:%.2f" % (i + 1, d) for i, d in enumerate(res.pre["dmg"]) if d > 0.001))
        prev = [l.dmg for l in self.layers]
        if any(d > 0.001 for d in prev):
            L.append("")
            L.append('damage D before the shot: ' + " ".join("%d:%.2f" % (i + 1, d) for i, d in enumerate(prev) if d > 0.001))
        if res.damage and any(d - p > 0.001 for d, p in zip(res.damage, prev + [0.0] * len(res.damage))):
            L.append('damage D after the shot: ' + " ".join("%d:%.2f" % (i + 1, d) for i, d in enumerate(res.damage) if d > 0.001))
        if res.imp and res.mode != "NORMAL":
            L.append("")
            L.append('acoustic interfaces (Tp = 4Z1Z2/(Z1+Z2)²):')
            for i, a1, b1, tp in res.imp:
                L.append("   %d %s→%s  Tp=%.2f%s" % (i + 1, a1, b1, tp, '  decoupling' if tp < 0.3 else ""))
        L.append("")
        L.append('LOS = path along the shot = thickness / cos(@)')
        L.append('Data are approximate, see README. The model does not replace')
        L.append('testing or a hydrocode.')
        return L


    # ------------------------------------------------------------- shots
    def _shot_task(self, task):
        s = self.shot
        if s.get("fire", True):
            self.fire()
        frac = s.get("t", 0.6)
        self.playing = False
        t0, t1 = self.world.t_total
        self.world.set_time(t0 + (t1 - t0) * frac)
        for _ in range(4):
            self.graphicsEngine.render_frame()
        self.win.save_screenshot(Filename(s["file"]))
        print("saved", s["file"])
        self.user_exit()
        return task.done


def main():
    shot = None
    if "--shot" in sys.argv:
        i = sys.argv.index("--shot")
        shot = dict(file=sys.argv[i + 1])
        if "--t" in sys.argv:
            shot["t"] = float(sys.argv[sys.argv.index("--t") + 1])
    app = App(shot)
    if shot:
        if "--preset" in sys.argv:
            app.load_preset(int(sys.argv[sys.argv.index("--preset") + 1]))
        if "--tab" in sys.argv:
            app.set_tab(sys.argv[sys.argv.index("--tab") + 1])
        if "--view" in sys.argv:
            az, el = sys.argv[sys.argv.index("--view") + 1].split(",")
            app.world.cam_az, app.world.cam_el = float(az), float(el)
            app.world.apply_camera()
        if "--tx" in sys.argv:
            app.world.cam_target.x = float(sys.argv[sys.argv.index("--tx") + 1])
            app.world.apply_camera()
        if "--zoom" in sys.argv:
            app.world.cam_dist = float(sys.argv[sys.argv.index("--zoom") + 1])
            app.world.apply_camera()
    app.run()
