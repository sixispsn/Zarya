"""
app/pz/scheme.py — принципиальная схема водоснабжения здания
по ГОСТ Р 21.619-2023, Приложение Б (поэтажная развёртка).

Приёмы оформления эталона Б:
  • стояк — ОСЬ помещения: вертикали В1/Т3 идут сквозь этажи по краю ячейки;
  • приборы подключены к стоякам подводками, УГО водоразборной арматуры;
  • примечания «в полу»/«в шахте», ПК-Б, вертикальные подписи стояков;
  • низ: ввод → узел учёта → насос → магистраль; кольцо циркуляции Т4 сверху.

ФАЗА A: раскладка приборов по этажам/помещениям автоматическая.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class SchemeFixture:
    name: str
    count: int
    dn: int = 15
    location: str = ""
    has_hot: bool = False


@dataclass
class SchemeRoom:
    name: str
    fixtures: List[SchemeFixture] = field(default_factory=list)
    has_pk: bool = False


@dataclass
class SchemeFloor:
    mark_m: float
    label: str
    rooms: List[SchemeRoom] = field(default_factory=list)


@dataclass
class BuildingScheme:
    floors: List[SchemeFloor] = field(default_factory=list)
    roof_mark: float = 10.0
    base_mark: float = -3.0
    inlet_dn: int = 50
    inlet_abs: float = -2.2
    meter_dn: int = 20
    has_pump: bool = False
    has_hot: bool = False
    has_fire: bool = False
    n_v1: int = 0
    n_t3: int = 0
    n_t4: int = 0


SYS = {"В1": "#1565c0", "Т3": "#c62828", "Т4": "#ef6c00", "В2": "#2e7d32"}


def _dist(count, n):
    base, rem = divmod(count, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def build_scheme_model(project) -> BuildingScheme:
    b = project.building
    n = max(1, b.floors_above or 1)
    h = b.height_m or n * 3.0
    fh = h / n
    m = BuildingScheme()
    m.roof_mark = round(n * fh, 1)
    m.has_hot = bool(b.hws_type and b.hws_type.value != "none")
    m.n_v1, m.n_t3, m.n_t4 = b.risers_v1 or 0, b.risers_t3 or 0, b.risers_t4 or 0

    san, kit = [], []
    for fg in (project.fixtures or []):
        nm = fg.name.lower()
        hot = ("умыв" in nm or "мойк" in nm or "душ" in nm)
        (kit if ("мойк" in nm or "кух" in nm) else san).append((fg, hot))

    for i in range(n):
        fl = SchemeFloor(mark_m=round(i * fh, 1), label=f"{i + 1} этаж")
        rs = SchemeRoom(name=f"Санузел {i + 1}.1", has_pk=True)
        for fg, hot in san:
            c = _dist(fg.count, n)[i]
            if c:
                loc = "в полу" if ("унитаз" in fg.name.lower() or "видуар" in fg.name.lower()) else ""
                rs.fixtures.append(SchemeFixture(fg.name, c, 15, loc, hot))
        if rs.fixtures:
            fl.rooms.append(rs)
        if kit:
            rk = SchemeRoom(name=f"Кафе {i + 1}.2")
            for fg, hot in kit:
                c = _dist(fg.count, n)[i]
                if c:
                    rk.fixtures.append(SchemeFixture(fg.name, c, 20, "", hot))
            if rk.fixtures:
                fl.rooms.append(rk)
        m.floors.append(fl)

    try:
        m.meter_dn = project.meters.rows[0].dn if project.meters and project.meters.rows else 20
    except Exception:
        m.meter_dn = 20
    m.inlet_dn = max(50, m.meter_dn)
    m.has_pump = bool(project.pumps and project.pumps.required)
    f = project.fire
    m.has_fire = bool(f and f.required)
    return m


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── УГО приборов ──
def _tap(x, y, color, up=True):
    """Водоразборный кран/смеситель: подводка + кран-уголок."""
    d = -1 if up else 1
    return (f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+d*12}" stroke="{color}" stroke-width="1.2"/>'
            f'<circle cx="{x}" cy="{y+d*12}" r="2.4" fill="white" stroke="{color}" stroke-width="1.2"/>'
            f'<line x1="{x}" y1="{y+d*14}" x2="{x+5}" y2="{y+d*18}" stroke="{color}" stroke-width="1.2"/>')


def _pk(x, y, color):
    """Пожарный кран ПК-Б: шкаф (квадрат) + кран."""
    return (f'<rect x="{x-6}" y="{y-6}" width="12" height="12" fill="none" stroke="{color}" stroke-width="1.2"/>'
            f'<circle cx="{x}" cy="{y}" r="2.5" fill="{color}"/>')


def render_scheme_svg(m: BuildingScheme, width: int = 1340) -> str:
    M_L, M_R, M_T = 150, 40, 70
    band_h = 165
    n = len(m.floors)
    plot_l, plot_r = M_L + 20, width - M_R
    y_roof = M_T + 30
    y_top = {}
    for idx in range(n):
        y_top[n - 1 - idx] = y_roof + idx * band_h
    y_base = y_roof + n * band_h + 26
    height = y_base + 175

    s: List[str] = []
    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
             f'font-family="Arial, sans-serif" font-size="11">')
    s.append(f'<rect width="{width}" height="{height}" fill="white"/>')
    s.append(f'<text x="{width/2:.0f}" y="34" text-anchor="middle" font-size="16" '
             f'font-weight="bold">Принципиальная схема водоснабжения здания</text>')

    def lab(x, y, t, sz=9, anc="middle", col="#333", bold=False, rot=None):
        w = ' font-weight="bold"' if bold else ''
        tr = f' transform="rotate({rot} {x:.0f} {y:.0f})"' if rot else ''
        return (f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="{anc}" font-size="{sz}" '
                f'fill="{col}"{w}{tr}>{_esc(t)}</text>')

    def hline(y, col="#333", w=1.0):
        return f'<line x1="{plot_l}" y1="{y:.0f}" x2="{plot_r}" y2="{y:.0f}" stroke="{col}" stroke-width="{w}"/>'

    def mark(y, mk, txt):
        t = ("{:+.1f}".format(mk)).replace(".", ",")
        return (f'<path d="M{M_L-6},{y-5:.0f} L{M_L},{y:.0f} L{M_L-6},{y+5:.0f} Z" fill="#333"/>'
                + lab(M_L - 10, y - 2, t, 9, "end", "#333", True)
                + lab(M_L - 10, y + 11, txt, 8, "end", "#555"))

    # колонки помещений (по этажу с макс. числом комнат)
    ncols = max((len(f.rooms) for f in m.floors), default=1) or 1
    col_w = (plot_r - plot_l) / ncols
    # x стояков для каждой колонки (правый край ячейки)
    def stack_x(j):
        return plot_l + (j + 1) * col_w - 34

    # ── кровля ──
    s.append(hline(y_roof, "#333", 1.2))
    s.append(mark(y_roof, m.roof_mark, "Кровля"))

    # ── стояки сквозь этажи (ось помещений) ──
    for j in range(ncols):
        sx = stack_x(j)
        # В1 (холодный)
        s.append(f'<line x1="{sx:.0f}" y1="{y_roof:.0f}" x2="{sx:.0f}" y2="{y_base:.0f}" '
                 f'stroke="{SYS["В1"]}" stroke-width="1.8"/>')
        s.append(lab(sx - 6, (y_roof + y_base) / 2, f"В1  Ø25", 8, "middle", SYS["В1"], True, rot=-90))
        # Т3 (горячий) — левее
        if m.has_hot:
            hx = sx - 16
            s.append(f'<line x1="{hx:.0f}" y1="{y_roof:.0f}" x2="{hx:.0f}" y2="{y_base:.0f}" '
                     f'stroke="{SYS["Т3"]}" stroke-width="1.6"/>')
            s.append(lab(hx - 6, (y_roof + y_base) / 2, f"Т3  Ø25", 8, "middle", SYS["Т3"], True, rot=-90))

    # кольцо циркуляции Т4 поверху (перемычка Т3→Т4 + балансир)
    if m.has_hot and m.n_t4:
        ty = y_roof + 14
        x1 = stack_x(0) - 16
        x2 = stack_x(ncols - 1) - 16
        s.append(f'<line x1="{x1:.0f}" y1="{ty:.0f}" x2="{x2:.0f}" y2="{ty:.0f}" '
                 f'stroke="{SYS["Т4"]}" stroke-width="1.4" stroke-dasharray="4 2"/>')
        s.append(lab((x1 + x2) / 2, ty - 4, f"циркуляция Т4 ({m.n_t4} шт)", 8, "middle", SYS["Т4"]))

    # ── этажные полосы, помещения, приборы ──
    for i in range(n):
        yt = y_top[i]
        yb = yt + band_h
        s.append(hline(yb, "#333", 1.0))
        s.append(mark(yb, m.floors[i].mark_m, m.floors[i].label))
        for j, room in enumerate(m.floors[i].rooms):
            cx0 = plot_l + j * col_w
            s.append(f'<rect x="{cx0:.0f}" y="{yt:.0f}" width="{col_w:.0f}" height="{band_h:.0f}" '
                     f'fill="none" stroke="#ddd" stroke-width="0.6"/>')
            s.append(lab(cx0 + col_w / 2, yt + 16, room.name, 9, "middle", "#333", True))
            sx = stack_x(j)
            hx = sx - 16
            pod_y = yb - 34          # уровень подводки (горизонталь)
            # подводка В1 от стояка влево
            s.append(f'<line x1="{cx0+30:.0f}" y1="{pod_y:.0f}" x2="{sx:.0f}" y2="{pod_y:.0f}" '
                     f'stroke="{SYS["В1"]}" stroke-width="1.2"/>')
            s.append(f'<circle cx="{sx:.0f}" cy="{pod_y:.0f}" r="2.4" fill="{SYS["В1"]}"/>')
            # подводка Т3 (если есть горячие приборы)
            has_hot_fx = any(fx.has_hot for fx in room.fixtures)
            if m.has_hot and has_hot_fx:
                s.append(f'<line x1="{cx0+30:.0f}" y1="{pod_y+10:.0f}" x2="{hx:.0f}" y2="{pod_y+10:.0f}" '
                         f'stroke="{SYS["Т3"]}" stroke-width="1.2"/>')
                s.append(f'<circle cx="{hx:.0f}" cy="{pod_y+10:.0f}" r="2.4" fill="{SYS["Т3"]}"/>')
            # приборы вдоль подводки
            xx = cx0 + 40
            for fx in room.fixtures:
                s.append(_tap(xx, pod_y, SYS["В1"], up=True))
                if fx.has_hot and m.has_hot:
                    s.append(_tap(xx + 6, pod_y + 10, SYS["Т3"], up=False))
                s.append(lab(xx, pod_y - 22, f"{fx.count} шт", 8, "middle", "#333"))
                s.append(lab(xx, pod_y + 26, f"Ø{fx.dn}", 7, "middle", "#777"))
                if fx.location:
                    s.append(lab(xx, pod_y + 36, fx.location, 7, "middle", "#999"))
                xx += 60
            # ПК-Б
            if room.has_pk and m.has_fire:
                s.append(_pk(cx0 + col_w - 50, pod_y - 6, SYS["В2"]))
                s.append(lab(cx0 + col_w - 50, pod_y + 14, "ПК-Б", 7, "middle", SYS["В2"]))

    # ── подвал ──
    s.append(hline(y_base, "#333", 1.0))
    s.append(mark(y_base, m.base_mark, "-1 этаж"))

    # магистраль внизу собирает В1-стояки
    sxs = [stack_x(j) for j in range(ncols)]
    if sxs:
        s.append(f'<line x1="{plot_l+160:.0f}" y1="{y_base:.0f}" x2="{max(sxs):.0f}" y2="{y_base:.0f}" '
                 f'stroke="{SYS["В1"]}" stroke-width="1.8"/>')

    # ── низ: ввод, узел учёта, насос ──
    uy = y_base + 36
    ux, uw, uh = plot_l + 50, 120, 34
    iy = uy + uh / 2
    s.append(f'<line x1="{M_L}" y1="{iy:.0f}" x2="{ux:.0f}" y2="{iy:.0f}" stroke="#333" stroke-width="1.6"/>')
    s.append(f'<path d="M{ux},{iy-4:.0f} L{ux-10},{iy:.0f} L{ux},{iy+4:.0f} Z" fill="#333"/>')
    s.append(lab(M_L + 4, iy - 8, f"Ввод водопровода Ø{m.inlet_dn}", 9, "start"))
    s.append(lab(M_L + 4, iy + 14, ("абс. отметка {:+.1f}".format(m.inlet_abs)).replace(".", ","), 8, "start", "#555"))
    s.append(f'<rect x="{ux:.0f}" y="{uy:.0f}" width="{uw}" height="{uh}" fill="#fafafa" stroke="#333"/>')
    s.append(lab(ux + uw / 2, uy + 14, "Узел учёта", 10, "middle", "#333", True))
    s.append(lab(ux + uw / 2, uy + 28, f"счётчик Ду{m.meter_dn}", 8, "middle", "#555"))
    feed_x = plot_l + 160
    if m.has_pump:
        px, pw = ux + uw + 36, 110
        s.append(f'<rect x="{px:.0f}" y="{uy:.0f}" width="{pw}" height="{uh}" fill="#fafafa" stroke="#333"/>')
        s.append(f'<circle cx="{px+pw/2:.0f}" cy="{uy+uh/2:.0f}" r="11" fill="white" stroke="#333"/>')
        s.append(f'<path d="M{px+pw/2-4:.0f},{uy+uh/2-5:.0f} L{px+pw/2+6:.0f},{uy+uh/2:.0f} '
                 f'L{px+pw/2-4:.0f},{uy+uh/2+5:.0f} Z" fill="#333"/>')
        s.append(lab(px + pw / 2, uy - 5, "Насосная станция", 9, "middle", "#333", True))
        s.append(f'<line x1="{px+pw:.0f}" y1="{iy:.0f}" x2="{feed_x:.0f}" y2="{iy:.0f}" stroke="{SYS["В1"]}" stroke-width="1.8"/>')
    else:
        s.append(f'<line x1="{ux+uw:.0f}" y1="{iy:.0f}" x2="{feed_x:.0f}" y2="{iy:.0f}" stroke="{SYS["В1"]}" stroke-width="1.8"/>')
    s.append(f'<line x1="{feed_x:.0f}" y1="{iy:.0f}" x2="{feed_x:.0f}" y2="{y_base:.0f}" stroke="{SYS["В1"]}" stroke-width="1.8"/>')

    # штриховка грунта
    gy = uy + uh + 22
    s.append(f'<line x1="{plot_l}" y1="{gy:.0f}" x2="{plot_r}" y2="{gy:.0f}" stroke="#333" stroke-width="1"/>')
    for gx in range(int(plot_l), int(plot_r), 20):
        s.append(f'<line x1="{gx}" y1="{gy:.0f}" x2="{gx-11}" y2="{gy+13:.0f}" stroke="#777" stroke-width="0.6"/>')

    # легенда
    ly = height - 18
    s.append(lab(plot_l, ly, "В1 — холодная", 8, "start", SYS["В1"], True))
    s.append(lab(plot_l + 110, ly, "Т3 — горячая (подача)", 8, "start", SYS["Т3"], True))
    s.append(lab(plot_l + 270, ly, "Т4 — циркуляция", 8, "start", SYS["Т4"], True))
    s.append(lab(plot_l + 400, ly, "В2/ПК — пожарный", 8, "start", SYS["В2"], True))

    s.append('</svg>')
    return "\n".join(s)


def generate_scheme_svg(project, path: str = None) -> str:
    svg = render_scheme_svg(build_scheme_model(project))
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    return svg
