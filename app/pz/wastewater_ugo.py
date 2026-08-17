"""Каталог УГО внутренних систем К1/К2/К3 и SVG-отрисовка.

Каталог разделяет три разных основания обозначений:

* нормативные УГО ГОСТ 21.205-2016;
* обозначения из рекомендуемого примера приложения В ГОСТ Р 21.620-2023;
* проектные обозначения, которые обязаны быть раскрыты в легенде листа.

Такое разделение не позволяет выдать локально принятое обозначение за
нормативное.  Геометрия УГО хранится в одном месте и используется схемой,
автоматической легендой и отдельным листом-ведомостью.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Dict, Iterable, List, Tuple

from app.pz.project import Project


BLACK = "#000"
GRAY = "#555"
FONT = "osifont"


@dataclass(frozen=True)
class UGOSymbolDefinition:
    key: str
    label: str
    basis: str
    status: str
    order: int

    @property
    def is_normative(self) -> bool:
        return self.status == "normative"

    @property
    def status_label(self) -> str:
        return {
            "normative": "нормативное УГО",
            "recommended": "рекомендуемый пример",
            "project": "проектное обозначение",
        }[self.status]


_DEFINITIONS: Tuple[UGOSymbolDefinition, ...] = (
    UGOSymbolDefinition("system_k1", "К1 - хозяйственно-бытовая канализация", "ГОСТ Р 21.620-2023, прил. В; марка системы по ГОСТ 21.205-2016", "recommended", 1),
    UGOSymbolDefinition("system_k2", "К2 - внутренний водосток", "ГОСТ Р 21.620-2023, прил. В; марка системы по ГОСТ 21.205-2016", "recommended", 2),
    UGOSymbolDefinition("system_k3", "К3 - производственная канализация", "ГОСТ Р 21.620-2023, прил. В; марка системы по ГОСТ 21.205-2016", "recommended", 3),
    UGOSymbolDefinition("sink", "мойка", "ГОСТ 21.205-2016, табл. 3, поз. 2 (вид для схем)", "normative", 10),
    UGOSymbolDefinition("washbasin", "умывальник", "ГОСТ 21.205-2016, табл. 3, поз. 3 (вид для схем)", "normative", 20),
    UGOSymbolDefinition("bath", "ванна", "ГОСТ 21.205-2016, табл. 3, поз. 7", "normative", 30),
    UGOSymbolDefinition("shower", "поддон душевой", "ГОСТ 21.205-2016, табл. 3, поз. 9", "normative", 40),
    UGOSymbolDefinition("toilet", "унитаз", "ГОСТ 21.205-2016, табл. 3, поз. 11", "normative", 50),
    UGOSymbolDefinition("floor_drain", "трап", "ГОСТ 21.205-2016, табл. 3, поз. 16", "normative", 60),
    UGOSymbolDefinition("roof_funnel", "воронка внутреннего водостока", "ГОСТ 21.205-2016, табл. 3, поз. 18", "normative", 70),
    UGOSymbolDefinition("roof_funnel_heated", "воронка внутреннего водостока с электрообогревом", "ГОСТ Р 21.620-2023, прил. В (обозначение в рекомендуемом примере; не отдельное УГО ГОСТ 21.205-2016)", "recommended", 71),
    UGOSymbolDefinition("trap", "сифон (гидрозатвор)", "ГОСТ 21.205-2016, табл. 4, поз. 4", "normative", 80),
    UGOSymbolDefinition("revision", "ревизия", "ГОСТ 21.205-2016, табл. 4, поз. 11", "normative", 90),
    UGOSymbolDefinition("pump", "насос (общее обозначение)", "ГОСТ 21.205-2016, табл. 2, поз. 3а", "normative", 100),
    UGOSymbolDefinition("check_valve", "клапан обратный", "ГОСТ 21.205-2016, табл. 6, поз. 5а", "normative", 110),
    UGOSymbolDefinition("ball_valve", "кран шаровой", "ГОСТ 21.205-2016, табл. 6, поз. 16", "normative", 120),
    UGOSymbolDefinition("flow_direction", "направление потока жидкости", "ГОСТ 21.205-2016, табл. 5, поз. 1", "normative", 130),
    UGOSymbolDefinition(
        "cleanout",
        "прочистка — заглушённый доступный конец",
        "Проектное обозначение по фактической конфигурации узла; признак — заглушённый доступный конец трубы или фасонной части",
        "project",
        200,
    ),
    UGOSymbolDefinition("fire_collar", "противопожарная муфта", "ГОСТ Р 21.620-2023, прил. В (обозначение в рекомендуемом примере; не УГО ГОСТ 21.205-2016)", "recommended", 210),
    UGOSymbolDefinition("sump", "приямок / приёмный резервуар", "ГОСТ Р 21.620-2023, п. 5.2.2.4; раскрывается в легенде", "project", 300),
    UGOSymbolDefinition("junction", "узел соединения", "Проектное обозначение; раскрывается в легенде", "project", 310),
    UGOSymbolDefinition("outlet", "выпуск", "ГОСТ Р 21.620-2023, п. 5.2.2.4; раскрывается в легенде", "project", 320),
    UGOSymbolDefinition("tee", "тройник", "Фактическая конфигурация трубопровода; раскрывается в легенде", "project", 330),
    UGOSymbolDefinition("elbow", "отвод", "Фактическая конфигурация трубопровода; раскрывается в легенде", "project", 340),
    UGOSymbolDefinition("transition", "переход", "Фактическая конфигурация трубопровода; раскрывается в легенде", "project", 350),
    UGOSymbolDefinition("other", "иной элемент", "Проектное обозначение; наименование задаёт проектировщик", "project", 900),
)

UGO_CATALOG: Dict[str, UGOSymbolDefinition] = {
    definition.key: definition for definition in _DEFINITIONS
}
# Local connection points are part of the symbol geometry, not a shared visual
# baseline.  Vector values below are the actual outlet endpoints after the
# nested source-PDF transforms used by ``_shape``.
UGO_CONNECTION_ANCHORS: Dict[str, Tuple[float, float]] = {
    "sink": (0.0, 21.927710844522),
    "washbasin": (0.0, 17.966595975755),
    "bath": (25.0, 19.0),
    "shower": (22.0, 16.0),
    "toilet": (0.0, 20.0),
    "floor_drain": (0.0, 10.0),
}
# Способ образования гидравлического затвора у санитарного прибора. Для
# приборов с отдельным сифоном генератор обязан поставить нормативное УГО
# по ГОСТ 21.205-2016, табл. 4, поз. 4 непосредственно в присоединение.
# У унитаза и трапа затвор является частью самого изделия, поэтому второй
# последовательный сифон на схеме был бы технически неверным.
FIXTURE_TRAP_MODES: Dict[str, str] = {
    "sink": "external",
    "washbasin": "external",
    "bath": "external",
    "shower": "external",
    "toilet": "integral",
    "floor_drain": "integral",
}
KIND_LABELS: Dict[str, str] = {
    definition.key: definition.label
    for definition in _DEFINITIONS
    if definition.key not in {
        "flow_direction", "system_k1", "system_k2", "system_k3",
        "roof_funnel_heated",
    }
}


def get_ugo_definition(kind: str) -> UGOSymbolDefinition:
    """Вернуть зарегистрированное определение; неизвестные ключи не скрывать."""
    try:
        return UGO_CATALOG[kind]
    except KeyError as exc:
        raise KeyError(f"неизвестный вид УГО: {kind}") from exc


def get_ugo_connection_anchor(kind: str) -> Tuple[float, float]:
    """Return the outlet point in the local coordinate system of an UGO."""
    try:
        return UGO_CONNECTION_ANCHORS[kind]
    except KeyError as exc:
        raise KeyError(f"для УГО {kind!r} не задана точка выпуска") from exc


def fixture_trap_mode(kind: str) -> str:
    """Вернуть ``external``, ``integral`` или ``none`` для вида элемента."""
    return FIXTURE_TRAP_MODES.get(kind, "none")


def legend_definitions(
    kinds: Iterable[str], *, include_flow_direction: bool = True
) -> List[UGOSymbolDefinition]:
    """Стабильная легенда только из фактически использованных видов элементов."""
    keys = {kind if kind in UGO_CATALOG else "other" for kind in kinds}
    if include_flow_direction:
        keys.add("flow_direction")
    return sorted((UGO_CATALOG[key] for key in keys), key=lambda row: row.order)


def project_legend_definitions(project: Project) -> List[UGOSymbolDefinition]:
    """Обозначения, реально применённые в проекте, включая марки систем."""
    elements = list(project.sewage.elements or [])
    keys = {
        row.kind if row.kind in UGO_CATALOG else "other"
        for row in elements
    }
    # Геометрические узлы и выпуск раскрываются надписями непосредственно на
    # схеме и не публикуются как будто это нормативные УГО.
    keys -= {"outlet", "junction", "tee", "elbow", "transition", "other"}
    heated = any(
        row.kind == "roof_funnel"
        and "электрообогрев" in (row.name or "").lower()
        for row in elements
    )
    if heated:
        keys.discard("roof_funnel")
        keys.add("roof_funnel_heated")
    # Сифоны являются частью графического узла подключения, поэтому у них
    # нет искусственных строк количества в реестре и спецификации. При этом
    # применённое УГО обязательно раскрывается в легенде листа.
    if any(fixture_trap_mode(row.kind) == "external" for row in elements):
        keys.add("trap")
    systems = {
        row.system.lower()
        for row in list(project.sewage.pipes or []) + elements
        if row.system in {"K1", "K2", "K3"}
    }
    keys.update(f"system_{system}" for system in systems)
    keys.add("flow_direction")
    return sorted((UGO_CATALOG[key] for key in keys), key=lambda row: row.order)


def _shape(kind: str) -> str:
    """Контур УГО в локальных координатах около (0, 0)."""
    s = BLACK
    sw = 2.2
    if kind in {"system_k1", "system_k2", "system_k3"}:
        mark = kind.split("_")[1].upper()
        return (
            f'<path d="M-28,0 H28" stroke="{s}" stroke-width="{sw}"/>'
            f'<rect x="-12" y="-8" width="24" height="16" fill="white"/>'
            f'<text x="0" y="5" text-anchor="middle" font-family="{FONT}" '
            f'font-size="12" font-weight="bold" fill="{s}">{mark}</text>'
        )
    if kind == "sink":
        # Исходный CAD-вектор извлечён из content stream векторной
        # аксонометрии ВК.pdf, лист 10. Координаты m/l не перерисовываются:
        # матрица ниже выполняет только перенос, инверсию PDF-оси Y и
        # равномерное масштабирование до локального размера УГО.
        return (
            '<g transform="matrix(0.313253012048 0 0 -0.313253012048 '
            '-1398.674698795181 1888.602409638554)">'
            f'<path d="M4382,6099 L4548,6099 M4536,6099 L4536,6004 '
            f'L4394,6004 L4394,6099 M4465,6004 L4465,5959" '
            f'fill="none" stroke="{s}" stroke-width="7.023076923077" '
            f'stroke-linecap="butt" stroke-linejoin="miter"/>'
            '</g>'
        )
    if kind == "washbasin":
        # Исходный CAD-вектор извлечён из content stream файла K-3.pdf,
        # лист 1, операции 25838-25860. Координаты линий, кубических кривых
        # Безье и залитого выпуска сохранены без ручной аппроксимации.
        return (
            '<g transform="matrix(0.057264050901 0 0 -0.057264050901 '
            '-846.677624602333 841.996288441145)">'
            f'<path d="M14314,15017 L15257,15017 '
            f'M14428,15017.5 C14428,14820.0586 14588.0586,14660 '
            f'14785.5,14660 C14982.9414,14660 15143,14820.0586 '
            f'15143,15017.5 M14439,14928 L15131,14928" '
            f'fill="none" stroke="{s}" stroke-width="38.421296296296" '
            f'stroke-linecap="butt" stroke-linejoin="miter"/>'
            f'<path d="M14797,14660 L14773,14660 L14797,14390 Z '
            f'M14773,14660 L14797,14390 L14773,14390 Z" fill="{s}"/>'
            '</g>'
        )
    if kind == "bath":
        return (
            f'<rect x="-27" y="-12.5" width="54" height="25" fill="none" '
            f'stroke="{s}" stroke-width="{sw}"/>'
            f'<path d="M-27,-12.5 L-12,12.5 M25,12.5 V19" fill="none" '
            f'stroke="{s}" stroke-width="{sw}"/>'
        )
    if kind == "shower":
        return (
            f'<rect x="-25" y="-9" width="50" height="18" fill="none" '
            f'stroke="{s}" stroke-width="{sw}"/>'
            f'<path d="M22,9 V16" stroke="{s}" stroke-width="{sw}"/>'
        )
    if kind == "toilet":
        # Канонический вариант для схем - таблица 3, позиция 11 ГОСТ
        # 21.205-2016.  Нижняя воронкообразная часть по высоте практически
        # равна прямоугольной верхней части; укороченный вариант из легенды
        # рекомендуемого примера приложения В здесь не применяется.
        return (
            f'<rect x="-12" y="-20" width="24" height="21" fill="white" '
            f'stroke="{s}" stroke-width="{sw}"/>'
            f'<path d="M-12,1 L0,20 L12,1 Z" fill="white" stroke="{s}" '
            f'stroke-width="{sw}"/>'
        )
    if kind == "floor_drain":
        return (
            f'<path d="M-21,-10 H21 L16,10 H-16 Z" fill="white" '
            f'stroke="{s}" stroke-width="{sw}"/>'
        )
    if kind == "roof_funnel":
        # Исходный CAD-вектор извлечён из предоставленного файла
        # «воронка.pdf». Координаты m/l/c сохранены буквально; матрица
        # выполняет только перенос, инверсию PDF-оси Y и масштабирование.
        return (
            '<g transform="matrix(0.008192524322 0 0 -0.008192524322 '
            '-38.197644649258 47.725550435228)">'
            f'<path d="M6400.38672,6147.68994 '
            f'C6245.09668,6985.32129 5514.4043,7593 4662.5,7593 '
            f'C3810.59546,7593 3079.90356,6985.32129 2924.61353,6147.68994 '
            f'M2924.61353,5503.31006 '
            f'C3079.90356,4665.67871 3810.59546,4058 4662.5,4058 '
            f'C5514.4043,4058 6245.09668,4665.67871 6400.38672,5503.31006 '
            f'M1733,6147 L2924,6147 M6400,6147 L7592,6147 '
            f'M1733,5503 L2924,5503 M6400,5503 L7592,5503 '
            f'M4662,4057 L4662,3045" fill="none" stroke="{s}" '
            f'stroke-width="268.5375" stroke-linecap="butt" '
            f'stroke-linejoin="miter"/>'
            '</g>'
        )
    if kind == "roof_funnel_heated":
        # Исходный CAD-вектор извлечён из предоставленного файла
        # «воронка с подогревом.pdf» без ручной аппроксимации контуров.
        return (
            '<g transform="matrix(0.015187470337 0 0 -0.015187470337 '
            '-77.547223540579 87.593735168486)">'
            f'<path d="M5833.61035,5902.11816 '
            f'C5768.63867,6252.09863 5462.92627,6506 5106.5,6506 '
            f'C4750.07373,6506 4444.36133,6252.09863 4379.38965,5902.11816 '
            f'M4379.38965,5632.88184 '
            f'C4444.36133,5282.90137 4750.07373,5029 5106.5,5029 '
            f'C5462.92627,5029 5768.63867,5282.90137 5833.61035,5632.88184 '
            f'M3881,5902 L4379,5902 M5832,5902 L6330,5902 '
            f'M3881,5633 L4379,5633 M5832,5633 L6330,5633 '
            f'M5106,5028 L5106,4605 '
            f'M7213,8174 L6334,7607 M6717,7514 L5606,6798 L5980,7157 '
            f'M5606,6798 L6088,6989 M6334,7607 L6717,7514 '
            f'M2999,8174 L3878,7607 M3494,7514 L4605,6798 L4232,7157 '
            f'M4605,6798 L4124,6989 M3878,7607 L3494,7514" '
            f'fill="none" stroke="{s}" stroke-width="144.85625" '
            f'stroke-linecap="butt" stroke-linejoin="miter"/>'
            '</g>'
        )
    if kind == "trap":
        return (
            f'<path d="M-14,-20 V9 Q-14,20 -4,20 Q5,20 5,9 V-8 '
            f'Q5,-19 14,-19 Q23,-19 23,-8 V20" fill="none" '
            f'stroke="{s}" stroke-width="{sw}"/>'
        )
    if kind == "revision":
        return (
            f'<path d="M-25,0 H25 M-22,-11 Q-8,0 -22,11" fill="none" '
            f'stroke="{s}" stroke-width="{sw}"/>'
            f'<circle cx="6" cy="0" r="4" fill="white" stroke="{s}" '
            f'stroke-width="{sw}"/>'
        )
    if kind == "cleanout":
        # The source cleanout detail varies with the node topology.  Only its
        # invariant feature is kept here: the pipe/fitting access end closed
        # by two parallel cap lines.  The path coordinates are taken from the
        # user-supplied vector reference ``прочистка.pdf``.
        return (
            '<g transform="matrix(0.007919485233 0 0 -0.007919485233 '
            '-39.506352087114 61.154264972777)">'
            f'<path d="M8019,7656 L2419,7656 M2419,8594 L2419,6850 '
            f'M1958,8594 L1958,6850" fill="none" stroke="{s}" '
            'stroke-width="277.795833333333" stroke-linecap="butt" '
            'stroke-linejoin="miter"/>'
            '</g>'
        )
    if kind == "fire_collar":
        return (
            f'<path d="M-25,0 H25" stroke="{s}" stroke-width="{sw}"/>'
            f'<rect x="-10" y="-6" width="20" height="12" fill="white" '
            f'stroke="{s}" stroke-width="{sw}"/>'
        )
    if kind == "pump":
        return (
            f'<path d="M0,-25 V-14 M0,14 V25" stroke="{s}" stroke-width="{sw}"/>'
            f'<circle cx="0" cy="0" r="14" fill="white" stroke="{s}" '
            f'stroke-width="{sw}"/>'
            f'<path d="M0,-12 L-5,-5 H5 Z" fill="{s}"/>'
        )
    if kind == "ball_valve":
        return (
            f'<path d="M-25,0 H-15 M15,0 H25 M-15,-11 L0,0 L-15,11 Z '
            f'M15,-11 L0,0 L15,11 Z" fill="white" stroke="{s}" '
            f'stroke-width="{sw}"/>'
            f'<circle cx="0" cy="0" r="5" fill="white" stroke="{s}" '
            f'stroke-width="{sw}"/>'
        )
    if kind == "check_valve":
        return (
            f'<path d="M-25,0 H-15 M15,0 H25 M-15,-11 L0,0 L-15,11 Z" '
            f'fill="{s}" stroke="{s}" stroke-width="{sw}"/>'
            f'<path d="M15,-11 L0,0 L15,11 Z" fill="white" stroke="{s}" '
            f'stroke-width="{sw}"/>'
        )
    if kind == "flow_direction":
        return (
            f'<path d="M-25,0 H-8 M8,0 H25" stroke="{s}" stroke-width="{sw}"/>'
            f'<path d="M-8,-9 L8,0 L-8,9 Z" fill="{s}"/>'
        )
    if kind == "sump":
        return (
            f'<path d="M-22,-14 V15 H22 V-14 M-16,6 Q-8,0 0,6 Q8,12 16,6" '
            f'fill="none" stroke="{s}" stroke-width="{sw}"/>'
        )
    if kind == "junction":
        return (
            f'<path d="M-24,0 H24 M0,-20 V20" stroke="{s}" '
            f'stroke-width="{sw}"/><circle cx="0" cy="0" r="4" fill="{s}"/>'
        )
    if kind == "outlet":
        return (
            f'<path d="M-25,0 H22" stroke="{s}" stroke-width="{sw}"/>'
            f'<path d="M22,0 L8,-8 M22,0 L8,8" fill="none" '
            f'stroke="{s}" stroke-width="{sw}"/>'
        )
    if kind == "tee":
        return f'<path d="M-23,0 H23 M0,0 V-20" fill="none" stroke="{s}" stroke-width="{sw}"/>'
    if kind == "elbow":
        return f'<path d="M-22,14 H0 Q14,14 14,0 V-18" fill="none" stroke="{s}" stroke-width="{sw}"/>'
    if kind == "transition":
        return f'<path d="M-24,-8 L0,-3 L24,-8 M-24,8 L0,3 L24,8" fill="none" stroke="{s}" stroke-width="{sw}"/>'
    return (
        f'<circle cx="0" cy="0" r="13" fill="white" stroke="{s}" '
        f'stroke-width="{sw}"/><text x="0" y="5" text-anchor="middle" '
        f'font-family="{FONT}" font-size="13" fill="{s}">Э</text>'
    )


def render_ugo(
    kind: str,
    x: float,
    y: float,
    *,
    scale: float = 1.0,
    rotation: float = 0.0,
    mirror_x: bool = False,
) -> str:
    """Нарисовать УГО; неизвестный вид явно показывается знаком «иной элемент»."""
    resolved = kind if kind in UGO_CATALOG else "other"
    scale_x = -scale if mirror_x else scale
    transform = (
        f"translate({x:.2f} {y:.2f}) rotate({rotation:.2f}) "
        f"scale({scale_x:.3f} {scale:.3f})"
    )
    return f'<g data-ugo="{escape(resolved)}" transform="{transform}">{_shape(resolved)}</g>'


def _wrap(value: str, width: int) -> List[str]:
    words = value.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def build_wastewater_ugo_sheet(project: Project) -> str:
    """Собрать лист А3 с нормативной трассировкой каждого УГО К1/К2/К3."""
    width, height = 1400, 990  # А3, альбомная ориентация 420×297 мм
    pxmm = width / 420
    doc = project.document
    body: List[str] = [f'<rect width="{width}" height="{height}" fill="white"/>']

    def line(x1, y1, x2, y2, sw=1.2, color=BLACK):
        body.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="{sw}"/>'
        )

    def rect(x, y, w, h, sw=1.2, fill="none"):
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" stroke="{BLACK}" stroke-width="{sw}"/>'
        )

    def text(x, y, value, size=11, anchor="start", weight="normal", color=BLACK):
        body.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}">{escape(str(value))}</text>'
        )

    left, right, top, bottom = 20 * pxmm, width - 5 * pxmm, 5 * pxmm, height - 5 * pxmm
    rect(left, top, right - left, bottom - top, 2.0)
    definitions = project_legend_definitions(project)
    system_label_by_key = {
        "system_k1": "К1",
        "system_k2": "К2",
        "system_k3": "К3",
    }
    system_labels = [
        system_label_by_key[key]
        for key in ("system_k1", "system_k2", "system_k3")
        if any(row.key == key for row in definitions)
    ]
    systems_title = ", ".join(system_labels) or "К1, К2, К3"
    text(
        left + 22,
        top + 38,
        f"Ведомость условных графических обозначений систем {systems_title}",
        20,
        weight="bold",
    )
    text(
        left + 22,
        top + 64,
        "УГО применяются на принципиальной схеме; локальные обозначения всегда раскрываются в легенде.",
        10,
        color=GRAY,
    )

    table_x = left + 22
    table_w = right - left - 44
    table_top = top + 92
    row_h = 55
    table_h = 34 + len(definitions) * row_h
    rect(table_x, table_top, table_w, table_h, 1.4)
    symbol_edge = table_x + 120
    name_edge = table_x + 455
    line(symbol_edge, table_top, symbol_edge, table_top + table_h)
    line(name_edge, table_top, name_edge, table_top + table_h)
    text(table_x + 60, table_top + 22, "УГО", 9.5, "middle", "bold")
    text((symbol_edge + name_edge) / 2, table_top + 22, "Наименование", 9.5, "middle", "bold")
    text(name_edge + (table_x + table_w - name_edge) / 2, table_top + 22, "Основание и статус", 9.5, "middle", "bold")
    line(table_x, table_top + 34, table_x + table_w, table_top + 34)
    for index, definition in enumerate(definitions):
        y0 = table_top + 34 + index * row_h
        if index:
            line(table_x, y0, table_x + table_w, y0, 0.9, "#777")
        body.append(render_ugo(definition.key, table_x + 60, y0 + row_h / 2, scale=0.82))
        name_lines = _wrap(definition.label, 42)[:2]
        for line_index, value in enumerate(name_lines):
            text(symbol_edge + 12, y0 + 23 + line_index * 14, value, 10, weight="bold")
        basis_lines = _wrap(definition.basis, 82)[:2]
        for line_index, value in enumerate(basis_lines):
            text(name_edge + 12, y0 + 19 + line_index * 13, value, 8.5)
        text(name_edge + 12, y0 + 48, definition.status_label, 7.5, color=GRAY)

    # Основная надпись: компактная форма 3 для самостоятельного листа А3.
    stamp_w, stamp_h = 185 * pxmm, 55 * pxmm
    sx, sy = right - stamp_w, bottom - stamp_h
    rect(sx, sy, stamp_w, stamp_h, 2.0, "white")
    label_w = 65 * pxmm
    line(sx + label_w, sy, sx + label_w, sy + stamp_h, 1.5)
    line(sx + label_w, sy + 33 * pxmm, right, sy + 33 * pxmm)
    line(sx + label_w, sy + 45 * pxmm, right, sy + 45 * pxmm)
    info_x = sx + label_w
    stage_x = right - 50 * pxmm
    sheet_x = right - 35 * pxmm
    total_x = right - 20 * pxmm
    for x in (stage_x, sheet_x, total_x):
        line(x, sy + 33 * pxmm, x, sy + stamp_h)
    text(sx + 8, sy + 24, "Разраб.", 8)
    text(sx + 8, sy + 48, _wrap(doc.developer_name or "", 22)[0], 8)
    text(info_x + (stage_x - info_x) / 2, sy + 24, _wrap(doc.cipher or "", 42)[0], 12, "middle", "bold")
    text(info_x + (stage_x - info_x) / 2, sy + 55, _wrap(doc.object_name or "", 48)[0], 8.5, "middle")
    text(info_x + (stage_x - info_x) / 2, sy + 91, f"Ведомость УГО систем {systems_title}", 9.5, "middle", "bold")
    for x0, x1, label in (
        (stage_x, sheet_x, "Стадия"),
        (sheet_x, total_x, "Лист"),
        (total_x, right, "Листов"),
    ):
        text((x0 + x1) / 2, sy + 126, label, 7, "middle")
    text((stage_x + sheet_x) / 2, sy + 162, doc.stage_label or "П", 11, "middle")
    text((sheet_x + total_x) / 2, sy + 162, doc.sheet_no or "2", 11, "middle")
    text((total_x + right) / 2, sy + 162, doc.sheet_total or "2", 11, "middle")

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
        f'viewBox="0 0 {width} {height}">' + "".join(body) + "</svg>"
    )
