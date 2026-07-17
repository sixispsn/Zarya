# -*- coding: utf-8 -*-
"""
app/pz/scheme.py — принципиальная схема систем В1, В2 (лист А1, штамп форма 3).

Точка входа: build_scheme(project: Project) -> SchemeResult(svg=...).
Обёртка эталонного движка (full_scheme v6) параметрами из модели Project:
  • этажность/отметки           — BuildingFlags (floors_above/below, height_m);
  • зоны водоснабжения          — building.zones (2 -> пары стояков В1.1/В1.2);
  • ПК, стояки В2, кольцо, ПТ   — FireSystem (required, pk_total);
  • насосная ПОЗ                — PumpSystem.required;
  • встроенные помещения цоколя — building.built_in_units;
  • санприборы квартирной ветки — project.fixtures (FixtureGroup);
  • ПЛК                         — flows.irrigation_m3_day > 0;
  • штамп форма 3               — project.document (185×55, геометрия document.html).
Чего в модели нет (Ду стояков/вводов, отметка ввода) — SchemeParams с дефолтами.

Компоновка листа (эталон): n≥4 -> полосы этажей «2, 3, n» с обрывом;
n≤3 -> полосы сплошняком, кровля на верхней. Цоколь (1 этаж) — всегда.
Узел вводов — по СП 30.13330.2020 п.8.5 (перемычка с задвижкой при 2 вводах).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from app.pz import ugo
from app.pz.annotate import Occ, place, text_w
from app.pz.project import Project

BLK = "#000"; FONT = "osifont"; DIA = "\u2205"
PIPE = 2.4; BLD = 1.2; LDR = 1.2; UGW = 2.0
W, H = 2803, 1980          # пропорция А1 (841×594)
PXMM = W / 841


@dataclass
class SchemeParams:
    """Параметры, отсутствующие в Project. Дефолты — эталонные, уточняются."""
    inlet_count: int = 2          # число вводов (2 -> перемычка с задвижкой, п.8.5)
    inlet_dn: int = 100           # Ду ввода
    inlet_abs: str = ""           # абс. отметка ввода, текст ("146,8")
    inlet_mark_m: float = -2.2    # относительная отметка ввода
    riser_v1_dn: int = 80         # Ду стояков В1 (шахтных)
    riser_v2_dn: int = 100        # Ду стояков В2
    floor_conn_dn: int = 32       # Ду поэтажной врезки от стояка
    apt_line_dn: int = 25         # Ду квартирной разводки
    plk_dn: int = 25              # Ду поливочного крана
    basement_depth_m: float = 4.0 # глубина -1 этажа (при floors_below>0)
    ground_h_m: float = 5.2       # высота цоколя (техпростр. над 1 этажом)
    title_line1: str = "Принципиальная схема"
    title_line2: str = "систем В1, В2"


@dataclass
class SchemeResult:
    svg: str
    width: int = W
    height: int = H
    warnings: List[str] = field(default_factory=list)


def _fmt_mark(v: float) -> str:
    """+5,200 / -4,000 — знак всегда, запятая, 3 знака."""
    return ("{:+.3f}".format(v)).replace(".", ",")


def build_scheme(project: Project, params: Optional[SchemeParams] = None) -> SchemeResult:
    P = params or SchemeParams()
    warns: List[str] = []
    b = project.building
    doc = project.document
    fire_on = bool(project.fire and project.fire.required)
    pump_on = bool(project.pumps and project.pumps.required)
    two_zones = (b.zones or 1) >= 2
    zone_regulators = list(getattr(
        getattr(project, "v1_hydraulic_result", None), "zone_regulators", []) or [])
    if (b.zones or 1) > 2:
        warns.append("расчётных зон больше двух: на принципиальной схеме показаны две характерные зоны")
    plk_on = bool(project.flows and project.flows.irrigation_m3_day > 0)
    n = max(1, b.floors_above or 1)
    fh = (b.height_m / n) if (b.height_m or 0) > 0 else 3.0

    # ── данные ВПВ из модели (FireSystem), а не из SchemeParams ──
    fire = project.fire
    # Ду стояка В2: если задан в params явно (>0) — уважаем; иначе выводим из
    # расхода по СП 10.13130.2020 (пропускная способность стояка):
    #   до 7,4 л/с — Ø65; 7,4..~12 — Ø80; выше — Ø100.
    if P.riser_v2_dn and params is not None and P.riser_v2_dn != SchemeParams.riser_v2_dn:
        v2_dn = P.riser_v2_dn                     # ручное переопределение
    elif fire_on:
        q = (fire.q_total or (fire.streams * fire.q_per_stream)) if fire else 0.0
        v2_dn = 65 if q <= 7.4 else (80 if q <= 12.0 else 100)
    else:
        v2_dn = P.riser_v2_dn
    fire_pk_total = (fire.pk_total if fire else 0) or 0
    fire_streams = (fire.streams if fire else 0) or 0
    has_aupt = bool(fire and fire.has_aupt)

    occ = Occ((W, H)); G: List[str] = []

    # ── низкоуровневые примитивы (эталон, без изменений геометрии) ──
    def pv(x, y1, y2, wd=PIPE, kind="pipe"):
        G.append(f'<line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" stroke="{BLK}" stroke-width="{wd}"/>')
        occ.add_line(x, min(y1, y2), x, max(y1, y2), kind)

    def ph(x1, x2, y, wd=PIPE, kind="pipe"):
        G.append(f'<line x1="{min(x1,x2):.1f}" y1="{y:.1f}" x2="{max(x1,x2):.1f}" y2="{y:.1f}" stroke="{BLK}" stroke-width="{wd}"/>')
        occ.add_line(min(x1, x2), y, max(x1, x2), y, kind)

    def txt(x, y, t, sz=13, anc="middle", reg=True):
        G.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{sz}" text-anchor="{anc}" fill="{BLK}">{t}</text>')
        if reg:
            tw = text_w(t, sz); x0 = x - tw / 2 if anc == "middle" else (x - tw if anc == "end" else x)
            occ.add(x0, y - sz, x0 + tw, y + 3)

    def dot(x, y, r=3.0): G.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{BLK}"/>')

    def arrow_down(x, y, s=7): G.append(f'<path d="M{x},{y} L{x-s*0.6},{y-s} L{x+s*0.6},{y-s} Z" fill="{BLK}"/>')

    def tilde(x, y):
        G.append(f'<path d="M{x-12},{y} q6,-8 12,0 q6,8 12,0" fill="none" stroke="{BLK}" stroke-width="{UGW}"/>')
        occ.add(x - 13, y - 9, x + 13, y + 9)

    def vyn(ax, ay, dx, dy, shelf, label, sz=12):
        kx, ky = ax + dx, ay + dy
        G.append(f'<line x1="{ax}" y1="{ay}" x2="{kx}" y2="{ky}" stroke="{BLK}" stroke-width="{LDR}"/>')
        x2 = kx + shelf
        G.append(f'<line x1="{min(kx,x2)}" y1="{ky}" x2="{max(kx,x2)}" y2="{ky}" stroke="{BLK}" stroke-width="{LDR}"/>')
        G.append(f'<text x="{min(kx,x2)+4}" y="{ky-4}" font-family="{FONT}" font-size="{sz}" fill="{BLK}">{label}</text>')
        occ.add(min(kx, x2), ky - sz - 4, max(kx, x2) + 4, ky + 4)

    def vbreak(x, y1, y2, label, cy=None, sz=13):
        yt, yb_ = min(y1, y2), max(y1, y2)
        if cy is None: cy = (yt + yb_) / 2
        tw = text_w(label, sz); gap = tw + 12
        pv(x, yt, cy - gap / 2); pv(x, cy + gap / 2, yb_)
        G.append(f'<text x="{x:.1f}" y="{cy:.1f}" font-family="{FONT}" font-size="{sz}" text-anchor="middle" dominant-baseline="middle" fill="{BLK}" transform="rotate(-90,{x:.1f},{cy:.1f})">{label}</text>')
        occ.add(x - sz, cy - tw / 2, x + sz, cy + tw / 2)

    def hbreak(x1, x2, y, label, cx=None, sz=13):
        if cx is None: cx = (x1 + x2) / 2
        tw = text_w(label, sz); gap = tw + 12
        ph(x1, cx - gap / 2, y); ph(cx + gap / 2, x2, y)
        txt(cx, y + 4, label, sz)

    def ph_gap(x1, x2, y, cuts, wd=PIPE, g=7):
        a, bb = min(x1, x2), max(x1, x2)
        pts = [a] + sorted([c for c in cuts if a + g < c < bb - g]) + [bb]
        segs = []; prev = a
        for c in pts[1:-1]:
            segs.append((prev, c - g)); prev = c + g
        segs.append((prev, bb))
        for s1, s2 in segs:
            if s2 > s1: ph(s1, s2, y, wd)

    def lbl(anchor, text, sz=12, maxr=420):
        s, box = place(occ, anchor, text, base_sz=sz, maxr=maxr)
        if s: G.append(s)
        else: warns.append("выноска не размещена: " + text[:60])

    def otm(x, y, mark, floor, sz=14):
        ph(x - 6, 200, y, 0.9, "bld")
        for sgn in (-1, 1):
            G.append(f'<line x1="{x+sgn*7}" y1="{y-9}" x2="{x}" y2="{y}" stroke="{BLK}" stroke-width="1.1"/>')
        G.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y-28}" stroke="{BLK}" stroke-width="1.1"/>')
        G.append(f'<line x1="{x-100}" y1="{y-28}" x2="{x}" y2="{y-28}" stroke="{BLK}" stroke-width="1.1"/>')
        txt(x - 4, y - 33, mark, sz, "end"); txt(x - 4, y - 12, floor, sz - 2, "end")

    # ── УГО (фикс размеры «квартирного типа», эталон) ──
    def valve_v(x, y): G.append(ugo.valve_v(x, y, tri=9, dot=4.5)); occ.add(x-9, y-9, x+9, y+9)
    def valve_h(x, y): G.append(ugo.valve_h(x, y, tri=9, dot=4.5)); occ.add(x-9, y-9, x+9, y+9)
    def filt_v(x, y): G.append(ugo.filt(x, y, hd=9, vd=9, ext=0, seg_n=3, rot=90)); occ.add(x-9, y-9, x+9, y+9)
    def filt_h(x, y): G.append(ugo.filt(x, y, hd=9, vd=9, ext=0, seg_n=3)); occ.add(x-9, y-9, x+9, y+9)
    def redv_v(x, y): G.append(ugo.redvalve(x, y, rw=14, rh=10, ext=0, apex="right", rot=-90)); occ.add(x-9, y-9, x+9, y+9)
    def redv_h(x, y, apex="right"): G.append(ugo.redvalve(x, y, rw=14, rh=10, ext=0, apex=apex)); occ.add(x-9, y-9, x+9, y+9)
    def meter_v(x, y): G.append(ugo.meter(x, y, rw=17, rh=11, ext=0, rot=90)); occ.add(x-9, y-9, x+9, y+9)
    def meter_h(x, y): G.append(ugo.meter(x, y, rw=17, rh=11, ext=0)); occ.add(x-9, y-9, x+9, y+9)
    def check_v(x, y): G.append(ugo.check_v(x, y, tri=9, flow="down")); occ.add(x-9, y-9, x+9, y+9)
    def flow_r(x, y, s=7): G.append(f'<path d="M{x},{y} L{x-s},{y-s*0.55} L{x-s},{y+s*0.55} Z" fill="{BLK}"/>')
    def gate_vv(x, y): G.append(ugo.gate_v(x, y, tri=10, bar=7)); occ.add(x-10, y-10, x+10, y+10)
    def gate_hh(x, y): G.append(ugo.gate_h(x, y, tri=10, bar=7)); occ.add(x-10, y-10, x+10, y+10)

    def pk_box(x, y, side="l", num=None):
        G.append(ugo.pk(x, y, r=12, w=UGW, conn=(side,))); occ.add(x-14, y-26, x+14, y+14)
        if num: txt(x, y - 30, "ПК-%d" % num, 11)

    S = 13; r_ = S * 0.32; OFF = (S + r_) + r_ + S * 1.4
    def washbasin(x, y, side="right"): G.append(ugo.washbasin(x, y, s=S, w=UGW, side=side)); occ.add(x-S, y-S*2.6, x+S, y)
    def shower(x, y, side): G.append(ugo.shower(x, y, s=S, w=UGW*0.85, side=side)); occ.add(x-S*1.6, y-S*2.8, x+S*1.6, y)

    def toilet_st(x, yb):
        yc = yb - OFF; bw, bh = 22, 13; yv = (yb + (yc + bh / 2)) / 2
        pv(x, yb, yc - bh / 2)
        G.append(f'<rect x="{x-bw/2}" y="{yc-bh/2}" width="{bw}" height="{bh}" fill="white" stroke="{BLK}" stroke-width="{UGW}"/>')
        valve_v(x, yv)

    def kran_leg(x, yb, side="left", h=16):
        if h > 0: pv(x, yb, yb - h)
        G.append(ugo.kran(x, yb - h, s=1.0, w=UGW, side=side)); occ.add(x-16, yb-h-16, x+16, yb)

    def spusknik_v(x, y_top):
        pv(x, y_top, y_top + 40); valve_v(x, y_top + 28)
        pv(x, y_top + 40, y_top + 50); arrow_down(x, y_top + 58)

    # ── набор санприборов квартирной ветки из project.fixtures ──
    def _fixture_set():
        has = {"toilet": False, "wash": False, "shower": False, "kran": False}
        for fg in (project.fixtures or []):
            nm = fg.name.lower()
            if "унитаз" in nm or "видуар" in nm: has["toilet"] = True
            elif "душ" in nm or "ванна" in nm: has["shower"] = True
            elif "умыв" in nm: has["wash"] = True
            elif "мойк" in nm or "кран" in nm or "фонтан" in nm: has["kran"] = True
        if not any(has.values()):   # приборов от АР нет — эталонный набор
            has = {"toilet": True, "wash": True, "shower": True, "kran": True}
        return has

    FIX = _fixture_set()

    # ================= ОБЩИЕ ОСИ ШАХТ =================
    SH1c, SH2c = 940, 1520
    LO1, HI1, V21 = SH1c - 24, SH1c, SH1c + 24
    V22, HI2, LO2 = SH2c - 24, SH2c, SH2c + 24
    XL, XR = 200, 2260; x_otm = 170

    # ================= КАРКАС (слоты полос) =================
    FLB = 260; RHf = 200; CHf = 56
    yF2, yF3, yFtop = 980, 720, 390        # эталонные слоты полос (низ полосы)
    with_rupture = n > 3
    # список видимых жилых этажей (номер, y-низ полосы), снизу вверх
    bands: List[tuple] = []
    if n >= 2: bands.append((2, yF2))
    if n >= 3: bands.append((3, yF3 if n > 3 else yF3))
    if n > 3: bands.append((n, yFtop))
    elif n == 3: bands[-1] = (3, yF3)
    # кровля: над верхней полосой (или над цоколем при n==1)
    y_tech = 1000; RHg = 250; y_0 = y_tech + RHg; CHg = 130; y_gb = y_0 + CHg
    y_m1 = 1730
    if bands:
        y_roof = (bands[-1][1] - FLB - 40) if not with_rupture else 90
    else:
        y_roof = y_tech - 40
    roof_mark = b.height_m if (b.height_m or 0) > 0 else P.ground_h_m + (n - 1) * fh + fh

    ph(XL, XR, y_m1, BLD, "bld"); ph(XL, XR, y_0, BLD, "bld"); ph(XL, XR, y_tech, BLD, "bld")
    ph(XL, XR, y_roof, BLD, "bld")
    pv(XL, y_roof, y_m1, BLD, "bld"); pv(XR, y_roof, y_m1, BLD, "bld")
    for _, yb_ in bands:
        ph(XL, XR, yb_, BLD, "bld"); ph(XL, XR, yb_ - FLB, BLD, "bld")

    has_m1 = (b.floors_below or 0) > 0
    otm(x_otm, y_m1, _fmt_mark(-P.basement_depth_m), "-1 этаж" if has_m1 else "Подвал")
    otm(x_otm, y_0, _fmt_mark(0.0), "1 этаж")
    otm(x_otm, y_tech, _fmt_mark(P.ground_h_m), "Тех. простр.")
    for k, yb_ in bands:
        otm(x_otm, yb_, _fmt_mark(P.ground_h_m + 0.7 + (k - 2) * fh), f"{k} этаж")
    otm(x_otm, y_roof, _fmt_mark(roof_mark), "Кровля")

    # ================= ЭТАЖНАЯ ПОЛОСА =================
    def floor_band(y_fl, pk_nums=(0, 0), last=False):
        y_rt = y_fl - FLB + 4; y_rb = y_rt + RHf; y_tr = y_rb + CHf // 2
        bx = [(200, 462, "Пом. 01; 02"), (472, 734, "Пом. 03; 04"), (744, 1054, None),
              (1064, 1242, "Мусорокамера" if b.purpose.value == "residential" else "Пом. С"),
              (1252, 1396, "Лифтовой холл"),
              (1406, 1716, None), (1726, 1988, "Пом. 05; 06"), (1998, 2260, "Пом. 07; 08")]
        for a, bb, nm in bx:
            G.append(f'<rect x="{a}" y="{y_rt}" width="{bb-a}" height="{RHf}" fill="none" stroke="{BLK}" stroke-width="{BLD}"/>')
            if nm: txt((a + bb) / 2, y_rt + 20, nm, 12)
            if nm == "Лифтовой холл": txt((a + bb) / 2, y_rt + 44, "Запотолочное пространство", 9)
        G.append(f'<rect x="{200}" y="{y_rb}" width="{2060}" height="{CHf}" fill="none" stroke="{BLK}" stroke-width="{BLD}"/>')

        def room(x0, x1, m):
            xr = (x1 - 30) if m > 0 else (x0 + 30)
            xa = xr - m * 40; y_hi = y_rt + 30; y_app = y_rt + RHf - 28
            dot(xr, y_tr); pv(xr, y_tr, y_hi); ph(xa, xr, y_hi); pv(xa, y_hi, y_app)
            dy = 24; ys = [y_hi + 14 + i * dy for i in range(5)]
            valve_v(xa, ys[0]); filt_v(xa, ys[1]); redv_v(xa, ys[2]); meter_v(xa, ys[3]); check_v(xa, ys[4])
            # приборы вдоль подводки — по составу из АР, шаг 34
            slot = 34; k = 1
            xend = xa
            if FIX["kran"]:
                kran_leg(xa - m * slot * k, y_app, "left" if m > 0 else "right", h=14); xend = xa - m * slot * k; k += 1
            if FIX["toilet"]:
                toilet_st(xa - m * slot * k, y_app); xend = xa - m * slot * k; k += 1
            if FIX["wash"]:
                washbasin(xa - m * slot * k, y_app - OFF, "right" if m > 0 else "left"); xend = xa - m * slot * k; k += 1
            if FIX["shower"]:
                _xd = xa - m * slot * k
                _edge = _xd - m * 3.27 * S
                if (m > 0 and _edge < x0 + 8) or (m < 0 and _edge > x1 - 8):
                    raise AssertionError("душ пересекает стену: ось=%.1f край=%.1f комната(%d,%d)" % (_xd, _edge, x0, x1))
                shower(_xd, y_app - OFF, "left" if m > 0 else "right"); xend = _xd
            ph(xend, xa, y_app)
            return xr

        def stub(x0, x1, m, hi, v2):
            xL = (x0 + 28) if m > 0 else (x1 - 28)
            dot(xL, y_tr); pv(xL, y_tr, (y_hi := y_rt + 30))
            ph(xL, hi, y_hi)
            redv_h(xL + m * 26, y_hi, apex="right" if m > 0 else "left")
            filt_h(xL + m * 54, y_hi)
            xdr = xL + m * 82; dot(xdr, y_hi); pv(xdr, y_hi, y_hi + 22, PIPE * 0.8); valve_v(xdr, y_hi + 15)
            valve_h(xL + m * 110, y_hi)
            dot(hi, y_hi)
            riser_tag = "В1.2" if two_zones else "В1"
            lab = riser_tag + DIA + str(P.floor_conn_dn); tw = text_w(lab, 12); gap = tw + 10
            cy = (y_rt + 12 + y_rb - 10) / 2 + 28
            y_top_r = (y_hi if last else y_rt + 12)
            pv(hi, y_top_r, cy - gap / 2); pv(hi, cy + gap / 2, y_rb - 10)
            G.append(f'<text x="{hi}" y="{cy}" font-family="{FONT}" font-size="12" text-anchor="middle" dominant-baseline="middle" fill="{BLK}" transform="rotate(-90,{hi},{cy})">{lab}</text>')
            if fire_on:
                pv(v2, y_rt + 12, y_fl)
            pv(hi, y_rb - 10, y_fl)
            if fire_on:
                y_pk = y_rt + RHf - 58
                dot(v2, y_pk); ph(v2, v2 + m * 22, y_pk, PIPE * 0.85)
                pk_box(v2 + m * 34, y_pk, side="l" if m > 0 else "r", num=(pk_nums[0] if m > 0 else pk_nums[1]))
            return xL

        apt_lab = ("В1.1.2" if two_zones else "В1.1") + DIA + str(P.apt_line_dn)
        xr01 = room(*bx[0][:2], +1); room(*bx[1][:2], +1)
        xL3 = stub(*bx[2][:2], +1, HI1, V21)
        hbreak(xr01, xL3, y_tr, apt_lab, sz=11)
        if b.purpose.value == "residential":
            xm = bx[3][0] + 30; ph(HI1, xm, y_rt + 30); y_kr = y_rt + RHf - 24
            pv(xm, y_rt + 30, y_kr)
            valve_v(xm, y_rt + 52); meter_v(xm, y_rt + 74); check_v(xm, y_rt + 96)
            ybr = y_rt + 118; dot(xm, ybr); ph(xm, xm + 40, ybr, PIPE * 0.85); valve_h(xm + 26, ybr)
            vyn(xm + 40, ybr, 14, -16, 86, "К прочистке ствола " + DIA + "20", 10)
            ph(xm, xm + 34, y_kr, PIPE * 0.85); kran_leg(xm + 34, y_kr, "right", h=12)
        xL6 = stub(*bx[5][:2], -1, HI2, V22)
        xr08 = room(*bx[7][:2], -1); room(*bx[6][:2], -1)
        hbreak(xL6, xr08, y_tr, apt_lab, sz=11)
        vyn(HI1, y_rt + 90, 20, -20, 36, "В шахте", 11)
        return y_rt

    # нумерация ПК: цоколь -> 1,2; далее по видимым этажам снизу вверх.
    # Схема принципиальная с обрывом — показывает ПК на характерных этажах,
    # а не все физические; полное число берётся из модели (fire.pk_total).
    pk_counter = 2 if fire_on else 0
    band_tops = []
    for i, (k, yb_) in enumerate(bands):
        nums = (pk_counter + 1, pk_counter + 2) if fire_on else (0, 0)
        pk_counter += 2 if fire_on else 0
        band_tops.append(floor_band(yb_, nums, last=(i == len(bands) - 1)))
    pk_shown = pk_counter
    if fire_on and not fire_pk_total:
        warns.append(f"на схеме показано ПК: {pk_shown} (характерные этажи); "
                     f"полное число определяется графической расстановкой по планам")
    elif fire_on and pk_shown < fire_pk_total:
        warns.append(f"на схеме показано ПК: {pk_shown} (характерные этажи); "
                     f"по расстановке всего {fire_pk_total} — обрыв этажей, это норма")
    elif fire_on and pk_shown > fire_pk_total:
        warns.append(f"на схеме ПК: {pk_shown} больше заданных {fire_pk_total} — проверить этажность/зоны")

    # межэтажные соединители (сквозные стояки между полосами и вниз к цоколю)
    riser_xs = ([HI1, HI2] + ([V21, V22] if fire_on else []))
    for i in range(len(bands) - 1, 0, -1):
        y_from = bands[i][1]; top_below = band_tops[i - 1]
        for xs in riser_xs: pv(xs, y_from, top_below + 12)
    if bands:
        for xs in riser_xs: pv(xs, bands[0][1], y_tech)

    # кольцо В2 поверху
    if fire_on and band_tops:
        y_ring = band_tops[-1] - 24
        pv(V21, band_tops[-1] + 12, y_ring); pv(V22, band_tops[-1] + 12, y_ring)
        hbreak(V21, V22, y_ring, "В2." + DIA + str(v2_dn), sz=11)

    # обрыв
    if with_rupture and len(bands) >= 2:
        def rupture(y, gap=24):
            G.append(f'<rect x="{XL-6}" y="{y}" width="{XR-XL+12}" height="{gap}" fill="white"/>')
            for yy in (y, y + gap):
                zz = (XL + 520, XR - 520)
                for a, bb in ((XL, zz[0] - 9), (zz[0] + 9, zz[1] - 9), (zz[1] + 9, XR)):
                    G.append(f'<line x1="{a}" y1="{yy}" x2="{bb}" y2="{yy}" stroke="{BLK}" stroke-width="0.9"/>')
                for z in zz:
                    G.append(f'<path d="M{z-9},{yy} l6,-12 l6,24 l6,-12" fill="none" stroke="{BLK}" stroke-width="0.9"/>')
            occ.add(XL, y, XR, y + gap)
        rupture((bands[-1][1] + (bands[-2][1] - FLB)) / 2)

    # ================= ЦОКОЛЬ (1 этаж) =================
    def ground():
        y_rt = y_tech; y_rb = y_0; y_mag = y_0 + CHg - 46
        # встроенные помещения из модели -> правый блок; левый — эталонный сервисный
        left = [(200, 440, "ПУИ", "pui", 1), (450, 660, "Санузел", "san", 1),
                (670, 880, "Мусорокамера" if b.purpose.value == "residential" else "Пом. С", "pui", 1)]
        mid = [(895, 985, "Шахта", None, 0), (995, 1465, "Вестибюль", None, 0), (1475, 1565, "Шахта", None, 0)]
        spans = [(1580, 1740), (1750, 1910), (1920, 2080), (2090, 2260)]
        units = list(b.built_in_units or [])
        if len(units) > len(spans):
            warns.append(f"встроек {len(units)}, на схеме показаны первые {len(spans)}")
            units = units[:len(spans)]
        right = []
        for i, (a, bb) in enumerate(spans):
            if i < len(units):
                u = units[i]
                nm = getattr(u, "name", "") or f"Встройка {i+1}"
                right.append((a, bb, nm, "t20", 1 if i < len(spans) - 1 else -1))
            else:
                right.append((a, bb, "Пом.", None, 0))
        bx = left + mid + right
        for a, bb, nm, _, _m in bx:
            G.append(f'<rect x="{a}" y="{y_rt}" width="{bb-a}" height="{RHg}" fill="none" stroke="{BLK}" stroke-width="{BLD}"/>')
            txt((a + bb) / 2, y_rt + 20, nm, 12)
        G.append(f'<rect x="{200}" y="{y_rb}" width="{2060}" height="{CHg}" fill="none" stroke="{BLK}" stroke-width="{BLD}"/>')
        # шахтные стояки сквозь цоколь и подвал — марки-номера
        v1tag = ("Ст.В1.1-%d", "Ст.В1.2-%d") if two_zones else (None, "Ст.В1-%d")
        stq = []
        if two_zones:
            stq += [(LO1, v1tag[0] % 1 + " " + DIA + str(P.riser_v1_dn), 1090),
                    (LO2, v1tag[0] % 2 + " " + DIA + str(P.riser_v1_dn), 1090)]
        stq += [(HI1, v1tag[1] % 1 + " " + DIA + str(P.riser_v1_dn), 1150),
                (HI2, v1tag[1] % 2 + " " + DIA + str(P.riser_v1_dn), 1150)]
        if fire_on:
            stq += [(V21, "Ст.В2-1 " + DIA + str(v2_dn), 1210),
                    (V22, "Ст.В2-2 " + DIA + str(v2_dn), 1210)]
        for xs, lab_, cy in stq: vbreak(xs, y_rt + 8, y_gb - 12, lab_, cy=cy, sz=11)
        x_up = 214
        ph(x_up, 2246, y_mag)      # магистраль нижней зоны
        if two_zones:
            dot(LO1, y_mag); dot(LO2, y_mag)
            for xs, dx in ((LO1, -26), (LO2, +26)):
                valve_v(xs, y_rb + 30)
                dot(xs, y_rb + 14); ph(xs, xs + dx, y_rb + 14)
                spusknik_v(xs + dx, y_rb + 14)

        def room_branch(x0, x1, kind, dn, m):
            xr = (x1 - 44) if m > 0 else (x0 + 36)
            dot(xr, y_mag); pv(xr, y_mag, y_rb)
            valve_v(xr, y_rb + 30)
            xd = xr - m * 26
            dot(xr, y_rb + 14); ph(xd, xr, y_rb + 14); spusknik_v(xd, y_rb + 14)
            y_hi = y_rt + int(RHg * 0.34)
            pv(xr, y_rb, y_hi)
            xa = xr - m * 40; ph(xa, xr, y_hi)
            y_app = y_rb - 30
            pv(xa, y_hi, y_app)
            dy = 25; ys = [y_hi + 14 + i * dy for i in range(5)]
            valve_v(xa, ys[0]); filt_v(xa, ys[1]); redv_v(xa, ys[2]); meter_v(xa, ys[3]); check_v(xa, ys[4])
            if kind.startswith("t"):
                tilde(xa, y_app)
            else:
                xend = xa - m * 112
                ph(xend, xa, y_app)
                washbasin(xa - m * 56, y_app - OFF, "right" if m > 0 else "left")
                if kind == "san": toilet_st(xend, y_app)
                else: kran_leg(xend, y_app, "left" if m > 0 else "right", h=14)
            vyn(xr, (y_rb + y_hi) / 2 + 26, m * 16, -20, m * 30, DIA + dn, 11)

        kinds = {"pui": "pui", "san": "san", "t20": "t", "t40": "t", "t32": "t", "t15": "t"}
        dnn = {"pui": "15", "san": "15", "t20": "20", "t40": "40", "t32": "32", "t15": "15"}
        for a, bb, nm, kd, m in bx:
            if kd: room_branch(a, bb, kinds[kd], dnn[kd], m)
        # ПЛК (поливочные краны) — при поливе в балансе
        if plk_on:
            valve_h(x_up + 120, y_mag); filt_h(x_up + 90, y_mag); redv_h(x_up + 60, y_mag); meter_h(x_up + 30, y_mag)
            pv(x_up, y_mag, y_rb); dot(x_up, y_mag)
            spusknik_v(x_up, y_mag)
            y_plk = y_rb - 30 - OFF - S - 12
            pv(x_up, y_rb, y_plk); ph(XL - 34, x_up, y_plk)
            kran_leg(XL - 34, y_plk, "left", h=0)
            vyn(XL - 34, y_plk - 24, -14, -22, -36, "ПЛК " + DIA + str(P.plk_dn), 11)
            x_upR = 2246
            valve_h(x_upR - 120, y_mag); filt_h(x_upR - 90, y_mag); redv_h(x_upR - 60, y_mag, apex="left"); meter_h(x_upR - 30, y_mag)
            pv(x_upR, y_mag, y_rb); dot(x_upR, y_mag)
            spusknik_v(x_upR, y_mag)
            pv(x_upR, y_rb, y_plk); ph(x_upR, XR + 34, y_plk)
            kran_leg(XR + 34, y_plk, "right", h=0)
            vyn(XR + 34, y_plk - 24, 14, -22, 36, "ПЛК " + DIA + str(P.plk_dn), 11)
        vyn(700, y_mag, -30, -26, -120, "Магистраль нижней зоны, в подвале", 10)
        return y_mag

    ymag_g = ground()

    # ================= НИЗ: вводы (п.8.5), транзит ПК, насосные =================
    ym = 1560; y_low = 1658
    xe = XL + 40
    inlet2 = P.inlet_count >= 2
    if inlet2:
        for yy in (ym - 34, ym + 34):
            ph(xe, xe + 66, yy); gate_hh(xe + 42, yy); flow_r(xe + 22, yy)
        pv(xe + 66, ym - 34, ym + 34); xA = xe + 66
        gate_vv(xA, ym - 17)               # задвижка на перемычке вводов (СП 30 п.8.5)
    else:
        ph(xe, xe + 66, ym); gate_hh(xe + 42, ym); flow_r(xe + 22, ym)
        xA = xe + 66
    dot(xA, ym)
    pv(xA + 38, ym, y_low); ph(xA, xA + 38, ym)
    ph(xA + 38, 2050, y_low)
    xfl = 1140
    ph(xA + 38, xfl + 22, y_low)
    # ПК-врезки СРАЗУ ПОСЛЕ ввода (до насосных), транзит по подвалу цоколя
    if fire_on:
        y_hif = y_tech + 24
        xt1, xt2 = 356, 378
        yh1, yh2 = 1356, 1372
        for xt, yh, xu in ((xt1, yh1, xfl), (xt2, yh2, xfl + 22)):
            dot(xt, y_low); pv(xt, y_low, yh)
            ph_gap(xt, xu, yh, [LO1, HI1, V21] if two_zones else [HI1, V21])
            pv(xu, yh, ymag_g + 7); pv(xu, ymag_g - 7, y_hif)
        xPK1, xPK2 = 1058, 1402
        ph(xPK1, xfl, y_hif)
        ph(xfl + 22, xPK2, y_hif)
        y_pk = y_0 - 54
        pv(xPK1, y_hif, y_pk); pv(xPK2, y_hif, y_pk)
        ph(xPK1 - 22, xPK1, y_pk); pk_box(xPK1 - 34, y_pk, side="r", num=1)
        ph(xPK2, xPK2 + 22, y_pk); pk_box(xPK2 + 34, y_pk, side="l", num=2)

    # насосные — помещениями в подвале
    yr_t = 1430; yr_b = y_m1

    def pump_room(xc, w_, name):
        a = xc - w_ / 2
        G.append(f'<rect x="{a}" y="{yr_t}" width="{w_}" height="{yr_b-yr_t}" fill="none" stroke="{BLK}" stroke-width="{BLD}"/>')
        occ.add(a, yr_t, a + w_, yr_b)
        txt(xc, yr_t + 22, name, 13, reg=False)
        txt(xc, yr_t + 42, "см. принципиальную схему", 10, reg=False)

    yj = y_gb + 22

    def draw_zone_regulator(index, x, y, *, vertical=True):
        if index >= len(zone_regulators):
            return
        regulator = zone_regulators[index]
        if not (regulator.required and regulator.topology_feasible):
            return
        if regulator.hydraulic_reserve_available is False:
            anchor = "end" if index == 0 and two_zones else "start"
            tx = x - 12 if anchor == "end" else x + 12
            txt(tx, y + 35, f"Зона {index + 1}:", 9, anchor, reg=False)
            txt(tx, y + 49, "отдельная НС", 9, anchor, reg=False)
            return
        if vertical:
            redv_v(x, y)
            anchor = "end" if index == 0 and two_zones else "start"
            tx = x - 16 if anchor == "end" else x + 16
            txt(tx, y - 5, f"РД-В1-{index + 1}", 10, anchor, reg=False)
            txt(tx, y + 9, f"Hвых={regulator.outlet_setpoint_m:.1f} м", 9,
                anchor, reg=False)
        else:
            redv_h(x, y)
            txt(x, y - 15, f"РД-В1-{index + 1}; Hвых={regulator.outlet_setpoint_m:.1f} м",
                9, "middle", reg=False)

    if pump_on:
        xpoz = xA + 360; pump_room(xpoz, 300, "Насосная станция ПОЗ")
        pv(xpoz, y_low, yr_t + 118); dot(xpoz, y_low); tilde(xpoz, yr_t + 118)
        outs = ((xpoz - 70, "lo"), (xpoz + 70, "hi")) if two_zones else ((xpoz + 70, "hi"),)
        for index, (xo, tag) in enumerate(outs):
            tilde(xo, yr_t + 96); pv(xo, yr_t + 96, yj if tag == "lo" else yj - 16)
            draw_zone_regulator(index, xo, yr_t + 62, vertical=True)
        if two_zones:
            ph(xpoz - 70, LO1, yj); pv(LO1, yj, y_gb - 2)
        ph(xpoz + 70, HI1, yj - 16); dot(HI1, yj - 16); ph(HI1, HI2, yj - 16)
        pv(HI1, yj - 16, y_gb - 2); pv(HI2, yj - 16, y_gb - 2)
    else:
        # без повысительной установки — магистраль напрямую к стоякам
        if two_zones:
            ph(xA + 38, LO1, yj); pv(LO1, yj, y_gb - 2); dot(LO1, yj)
            draw_zone_regulator(0, xA + 105, yj, vertical=False)
        ph(xA + 38, HI1, yj - 16); dot(HI1, yj - 16); ph(HI1, HI2, yj - 16)
        draw_zone_regulator(1 if two_zones else 0, xA + 145, yj - 16, vertical=False)
        pv(HI1, yj - 16, y_gb - 2); pv(HI2, yj - 16, y_gb - 2)
    if fire_on:
        xpt = (xA + 360 + 640) if pump_on else (xA + 700)
        pump_room(xpt, 300, "Насосная станция пожаротушения")
        pv(xpt, y_low, yr_t + 118); dot(xpt, y_low); tilde(xpt, yr_t + 118)
        yv = yj + 16
        for xo, xg in ((xpt - 70, V21), (xpt + 70, V22)):
            tilde(xo, yr_t + 96); pv(xo, yr_t + 96, yv); ph(min(xo, xg), max(xo, xg), yv); pv(xg, yv, y_gb - 2)

    # выноски низа
    inlet_txt = (f"Ввод водопровода {P.inlet_count}x{DIA}{P.inlet_dn}"
                 + (f", абс. отметка {P.inlet_abs} ({_fmt_mark(P.inlet_mark_m)})" if P.inlet_abs
                    else f", отм. {_fmt_mark(P.inlet_mark_m)}"))
    lbl((xe + 33, ym + (34 if inlet2 else 0)), inlet_txt, 11)
    if fire_on:
        lbl((378, 1470), f"На пожаротушение нижней зоны {P.inlet_count}x{DIA}{P.inlet_dn}", 11, maxr=480)
    vyn(1900, y_low, 26, -26, 44, "отм. " + _fmt_mark(-(P.basement_depth_m - 0.6)), 11)
    vyn(1250, y_0 + CHg - 46, 24, -22, 44, "отм. -0,700", 11)
    if fire_on:
        vyn(1250, y_tech + 24, 22, 26, 44, "отм. " + _fmt_mark(P.ground_h_m - 0.2), 11)

    # ================= РАМКА + ШТАМП ФОРМА 3 (из project.document) =================
    fx0, fy0, fx1, fy1 = 20 * PXMM, 5 * PXMM, W - 5 * PXMM, H - 5 * PXMM
    G.append(f'<rect x="{fx0:.1f}" y="{fy0:.1f}" width="{fx1-fx0:.1f}" height="{fy1-fy0:.1f}" fill="none" stroke="{BLK}" stroke-width="2"/>')

    def mmx(v): return fx1 - (185 - v) * PXMM
    def mmy(v): return fy1 - (55 - v) * PXMM
    def L(x1, y1, x2, y2, w=1.0): G.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{BLK}" stroke-width="{w}"/>')
    def T(x, y, t, sz=9, anc="middle"): G.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{sz}" text-anchor="{anc}" fill="{BLK}">{t}</text>')

    G.append(f'<rect x="{mmx(0):.1f}" y="{mmy(0):.1f}" width="{185*PXMM:.1f}" height="{55*PXMM:.1f}" fill="white" stroke="{BLK}" stroke-width="2"/>')
    L(mmx(65), mmy(0), mmx(65), mmy(55), 1.6)
    for cx in (7, 17, 25, 37, 53): L(mmx(cx), mmy(0), mmx(cx), mmy(25))
    for cx in (17, 37, 53): L(mmx(cx), mmy(25), mmx(cx), mmy(55))
    L(mmx(135), mmy(25), mmx(135), mmy(55), 1.3)
    for cx in (150, 165): L(mmx(cx), mmy(25), mmx(cx), mmy(40))
    for yy in range(5, 55, 5): L(mmx(0), mmy(yy), mmx(65), mmy(yy))
    L(mmx(65), mmy(10), mmx(185), mmy(10))
    L(mmx(65), mmy(25), mmx(185), mmy(25))
    L(mmx(135), mmy(30), mmx(185), mmy(30))
    L(mmx(65), mmy(40), mmx(185), mmy(40))
    for t, c0, c1 in (("Изм.", 0, 7), ("Кол.уч.", 7, 17), ("Лист", 17, 25), ("№ док.", 25, 37), ("Подп.", 37, 53), ("Дата", 53, 65)):
        T(mmx((c0 + c1) / 2), mmy(25) - 4, t, 8)
    signers = (("Разраб.", doc.developer_name, 30), ("Проверил", doc.inspector_name, 35),
               ("Нач. отдела", doc.dept_head_name, 40), ("ГИП", doc.gip_name, 45),
               ("Н. контр.", doc.norm_control_name, 55))
    for t, nm, row in signers:
        T(mmx(1) + 2, mmy(row) - 4.5, t, 8.5, "start")
        if nm: T(mmx(27), mmy(row) - 4.5, nm, 8.5)
    T(mmx(125), mmy(8), doc.cipher or "⟦ШИФР⟧", 15.5)
    T(mmx(125), mmy(19), doc.object_name or "⟦ОБЪЕКТ⟧", 9.5)
    T(mmx(100), mmy(34.5), doc.object_part or "⟦ЧАСТЬ⟧", 12)
    T(mmx(142.5), mmy(30) - 4, "Стадия", 7.5); T(mmx(157.5), mmy(30) - 4, "Лист", 7.5); T(mmx(175), mmy(30) - 4, "Листов", 7.5)
    T(mmx(142.5), mmy(37), doc.stage_label or "П", 11)
    T(mmx(157.5), mmy(37), doc.sheet_no or "1", 11)
    T(mmx(175), mmy(37), doc.sheet_total or "1", 11)
    T(mmx(100), mmy(46.5), P.title_line1, 12)
    T(mmx(100), mmy(52.5), P.title_line2, 12)
    T(mmx(160), mmy(49), doc.organization or "⟦ОРГАНИЗАЦИЯ⟧", 10)
    # боковая графа (25|35|25, снизу вверх)
    bg = fx0 - 12 * PXMM
    for h0, h1, t in ((0, 25, "Инв. № подл."), (25, 60, "Подп. и дата"), (60, 85, "Взам. инв. №")):
        y0 = fy1 - h0 * PXMM; y1 = fy1 - h1 * PXMM
        G.append(f'<rect x="{bg:.1f}" y="{y1:.1f}" width="{12*PXMM:.1f}" height="{(h1-h0)*PXMM:.1f}" fill="none" stroke="{BLK}" stroke-width="1.3"/>')
        cyb = (y0 + y1) / 2
        G.append(f'<text x="{bg+6*PXMM:.1f}" y="{cyb:.1f}" font-family="{FONT}" font-size="9.5" text-anchor="middle" dominant-baseline="middle" fill="{BLK}" transform="rotate(-90,{bg+6*PXMM:.1f},{cyb:.1f})">{t}</text>')

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
           f'<rect width="{W}" height="{H}" fill="white"/>{"".join(G)}</svg>')
    return SchemeResult(svg=svg, warnings=warns)


def render_scheme_png(result: SchemeResult, path: str, scale: float = 1.7) -> str:
    """PNG для контроля (пиксельный аудит). cairosvg — опциональная зависимость."""
    import cairosvg
    cairosvg.svg2png(bytestring=result.svg.encode(), write_to=path, scale=scale)
    return path
