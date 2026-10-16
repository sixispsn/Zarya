"""
app/pz/pump_chart.py — генератор графика Q-H для пояснительной записки.

Рендер каталожной кривой, расчётной точки и, при наличии данных, оценки сети.
Поиск точки использует общий модуль L04. Никакой селекции насоса здесь нет — её делает
flows_bridge.pump_from_calc (ядро Антона). Этот модуль ТОЛЬКО рисует
то, что ему передали, и отдаёт строку SVG для вставки в шаблон:

    {{ pump_chart_svg | safe }}

WeasyPrint-специфика (из STATUS.md «Ключевые технические решения»):
- корневой <svg> несёт явные width/height в мм + viewBox — иначе WeasyPrint
  рендерит SVG нулевого размера;
- вместо rgba() используем fill/stroke + fill-opacity/stroke-opacity
  (надёжнее в SVG-движке WeasyPrint);
- SVG инлайнится в HTML напрямую, base_url для него не нужен.

Исправление L02: разложение напора приходит из ядра без повторного расчёта.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from xml.sax.saxutils import escape
from app.calc.pump_system_curve import required_boost_head
from app.calc.pump_curve import find_intersections, interpolate_head

# Точка кривой: (Q, м³/ч; H, м)
Point = tuple[float, float]


# ── Геометрия системы и рабочая точка (порт JS) ──────────────────────────

def interp_h(curve: Sequence[Point], q: float) -> float | None:
    """Общий интерполятор L04; отсутствие данных не является нулём напора."""
    return interpolate_head(curve, q)


def build_effective_curve(curve: Sequence[Point], mode: str) -> list[Point]:
    """Кривая с учётом схемы включения (порт buildEffectiveCurve).

    mode: '1' — один; '2p' — параллельно (Q×2 при том же H);
          '2s' — последовательно (H×2 при том же Q).
    """
    if mode == "2p":
        return [(q * 2, h) for q, h in curve]
    if mode == "2s":
        return [(q, h * 2) for q, h in curve]
    return list(curve)


def find_working_point(curve: Sequence[Point], h_stat: float,
                       k_sys: float, steps: int = 200) -> Point | None:
    """Общий поиск L04. steps оставлен для совместимости, сетка не применяется."""
    wp = find_intersections(curve, h_stat, k_sys).working_point
    return (wp.q, wp.h) if wp else None


# ── Параметры графика ────────────────────────────────────────────────────

@dataclass
class PumpChart:
    """Всё, что нужно нарисовать. Заполняется из flows_bridge.pump_from_calc."""
    curve: list[Point]                 # эффективная кривая (уже с учётом mode)
    h_stat: float | None               # signed intercept; None = нет разложения
    k_sys: float | None
    wp: Point | None = None            # рабочая точка (Q, H); None — не считать
    q_opt: float | None = None         # BEP насоса, м³/ч (для полосы КПД)
    title: str = ""                    # подпись, напр. "Grundfos Hydro MPC-E CR15-9"
    # масштаб в PDF
    width_mm: float = 165.0
    font_family: str = "Times New Roman, serif"
    duty: Point | None = None          # требуемая расчётная точка, не пересечение


# ── Рендер SVG (порт drawChart) ──────────────────────────────────────────

# Внутренний холст идентичен JS-версии
_W, _H = 600, 320
_PAD = {"left": 55, "right": 20, "top": 20, "bottom": 45}
_CW = _W - _PAD["left"] - _PAD["right"]
_CH = _H - _PAD["top"] - _PAD["bottom"]


def render_pump_chart_svg(chart: PumpChart) -> str:
    height_mm = chart.width_mm * _H / _W
    ff = escape(chart.font_family, {'"': "&quot;"})
    open_tag = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{chart.width_mm:.1f}mm" height="{height_mm:.1f}mm" '
        f'viewBox="0 0 {_W} {_H}" font-family="{ff}">'
    )

    if not chart.curve:
        return (
            f'{open_tag}<text x="300" y="160" text-anchor="middle" '
            f'fill="#aaa" font-size="14">Нет данных для построения графика</text></svg>'
        )

    q_max = chart.curve[-1][0] * 1.1
    h_max = max(chart.curve[0][1], chart.duty[1] if chart.duty else 0) * 1.15
    if chart.duty:
        q_max = max(q_max, chart.duty[0] * 1.1)
    if q_max <= 0 or h_max <= 0:
        return f'{open_tag}</svg>'

    pl, pt = _PAD["left"], _PAD["top"]

    def sx(q: float) -> float:
        return pl + (q / q_max) * _CW

    def sy(h: float) -> float:
        return pt + _CH - (h / h_max) * _CH

    out: list[str] = [open_tag]

    # Фон поля
    out.append(f'<rect x="{pl}" y="{pt}" width="{_CW}" height="{_CH}" '
               f'fill="#fafafa" stroke="#ddd"/>')

    # Полоса BEP (0.7–1.1 × Q_opt)
    if chart.q_opt:
        bx1 = sx(max(0.0, chart.q_opt * 0.7))
        bx2 = sx(min(q_max, chart.q_opt * 1.1))
        out.append(f'<rect x="{bx1:.1f}" y="{pt}" width="{bx2 - bx1:.1f}" '
                   f'height="{_CH}" fill="#f39c12" fill-opacity="0.10" '
                   f'stroke="#f39c12" stroke-opacity="0.3" stroke-dasharray="4,3"/>')
        out.append(f'<text x="{(bx1 + bx2) / 2:.1f}" y="{pt + 12}" '
                   f'text-anchor="middle" font-size="9" fill="#f39c12">BEP</text>')

    # Сетка + подписи осей (по 5 делений)
    for i in range(6):
        y = pt + (_CH / 5) * i
        h_val = h_max * (1 - i / 5)
        out.append(f'<line x1="{pl}" y1="{y:.1f}" x2="{pl + _CW}" y2="{y:.1f}" '
                   f'stroke="#e0e0e0" stroke-width="1"/>')
        out.append(f'<text x="{pl - 6}" y="{y + 4:.1f}" text-anchor="end" '
                   f'font-size="10" fill="#888">{h_val:.0f}</text>')
    for i in range(6):
        x = pl + (_CW / 5) * i
        q_val = q_max * i / 5
        out.append(f'<line x1="{x:.1f}" y1="{pt}" x2="{x:.1f}" y2="{pt + _CH}" '
                   f'stroke="#e0e0e0" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{pt + _CH + 16}" text-anchor="middle" '
                   f'font-size="10" fill="#888">{q_val:.1f}</text>')

    # Оси
    out.append(f'<line x1="{pl}" y1="{pt}" x2="{pl}" y2="{pt + _CH}" '
               f'stroke="#888" stroke-width="1.5"/>')
    out.append(f'<line x1="{pl}" y1="{pt + _CH}" x2="{pl + _CW}" y2="{pt + _CH}" '
               f'stroke="#888" stroke-width="1.5"/>')
    yc = pt + _CH / 2
    out.append(f'<text x="{pl - 35}" y="{yc:.1f}" text-anchor="middle" '
               f'font-size="11" fill="#555" '
               f'transform="rotate(-90,{pl - 35},{yc:.1f})">H, м</text>')
    out.append(f'<text x="{pl + _CW / 2}" y="{_H - 5}" text-anchor="middle" '
               f'font-size="11" fill="#555">Q, м³/ч</text>')

    # Кривая системы H=H_стат+k·Q²
    if chart.h_stat is not None and chart.k_sys is not None:
        sys_pts = []
        samples = [q_max * i / 160 for i in range(161)]
        if chart.duty:
            samples.append(chart.duty[0])  # точная привязка, не ближайший пиксель сетки
        for q in sorted(set(samples)):
            h = required_boost_head(chart.h_stat, chart.k_sys, q)
            if h <= h_max:
                sys_pts.append(f'{sx(q):.1f},{sy(h):.1f}')
        out.append(f'<polyline data-role="system-curve" points="{" ".join(sys_pts)}" fill="none" '
                   f'stroke="#c0392b" stroke-width="2" stroke-dasharray="6,3"/>')

    # Кривая насоса
    pump_pts = [f'{sx(q):.1f},{sy(h):.1f}' for q, h in chart.curve]
    out.append(f'<polyline points="{" ".join(pump_pts)}" fill="none" '
               f'stroke="#1a6aaa" stroke-width="2.5"/>')

    if chart.duty:
        dx, dy = sx(chart.duty[0]), sy(chart.duty[1])
        out.append(f'<path data-role="design-point" d="M{dx-5:.1f},{dy:.1f} '
                   f'L{dx+5:.1f},{dy:.1f} M{dx:.1f},{dy-5:.1f} L{dx:.1f},{dy+5:.1f}" '
                   f'stroke="#b55a00" stroke-width="2"/>')
        out.append(f'<text x="{pl + _CW - 5}" y="{pt + 32}" text-anchor="end" '
                   f'font-size="10" fill="#b55a00">Расчётная точка Q/H</text>')

    # Рабочая точка
    if chart.wp:
        wq, wh = chart.wp
        wx, wy = sx(wq), sy(wh)
        out.append(f'<line x1="{wx:.1f}" y1="{wy:.1f}" x2="{wx:.1f}" '
                   f'y2="{pt + _CH}" stroke="#27ae60" stroke-width="1" '
                   f'stroke-dasharray="3,3"/>')
        out.append(f'<line x1="{pl}" y1="{wy:.1f}" x2="{wx:.1f}" y2="{wy:.1f}" '
                   f'stroke="#27ae60" stroke-width="1" stroke-dasharray="3,3"/>')
        out.append(f'<circle cx="{wx:.1f}" cy="{wy:.1f}" r="7" '
                   f'fill="#27ae60" fill-opacity="0.25"/>')
        out.append(f'<circle data-role="working-point" cx="{wx:.1f}" cy="{wy:.1f}" r="4" fill="#27ae60"/>')
        # Плашка с подписью; клампим вправо/вверх, чтобы не уходила за поле PDF
        lbl_w = 92
        lx = min(wx + 8, pl + _CW - lbl_w)
        ly = max(wy - 8, pt + 14)
        out.append(f'<rect x="{lx - 2:.1f}" y="{ly - 12:.1f}" width="{lbl_w}" '
                   f'height="28" rx="3" fill="white" fill-opacity="0.85"/>')
        out.append(f'<text x="{lx + 2:.1f}" y="{ly:.1f}" font-size="10" '
                   f'fill="#1a7a30" font-weight="600">Q={wq:.2f} м³/ч</text>')
        out.append(f'<text x="{lx + 2:.1f}" y="{ly + 12:.1f}" font-size="10" '
                   f'fill="#1a7a30" font-weight="600">H={wh:.1f} м</text>')

    # Заголовок
    if chart.title:
        out.append(f'<text x="{pl + 10}" y="{pt + 18}" font-size="11" '
                   f'fill="#1a6aaa" font-weight="600">{escape(chart.title)}</text>')

    out.append("</svg>")
    return "".join(out)
