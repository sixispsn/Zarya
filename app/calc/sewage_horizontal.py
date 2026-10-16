"""СП 30.13330.2020, 5.7(7), table 5.1: horizontal domestic drains.

Not the riser formula 5.5, not a sum of riser maxima and not daily flow / 24.
L has the specific meaning in the table footnote, not a drawing/polyline length.
Interpolation inside table 5.1 was explicitly approved on 2026-10-07.
It is an engineering table-processing method, not a quoted SP requirement.
No extrapolation, rounding of N/L, or substitution N=inhabitants.
"""
from bisect import bisect_left
from dataclasses import dataclass
from math import isfinite

LENGTHS_M = (1, 3, 5, 7, 10, 15, 20, 30, 40, 50, 100, 500, 1000)
KS_ROWS = {
    4: (.61,.51,.46,.43,.40,.36,.34,.31,.27,.25,.23,.15,.13),
    8: (.63,.53,.48,.45,.41,.37,.35,.32,.28,.26,.24,.16,.13),
    12: (.64,.54,.49,.46,.42,.39,.36,.33,.29,.26,.24,.16,.14),
    16: (.65,.55,.50,.47,.43,.39,.37,.33,.30,.27,.25,.17,.14),
    20: (.66,.56,.51,.48,.44,.40,.38,.34,.30,.28,.25,.17,.14),
    24: (.67,.57,.52,.48,.45,.41,.38,.35,.31,.28,.26,.17,.15),
    28: (.68,.58,.53,.49,.46,.42,.39,.36,.31,.29,.27,.18,.15),
    32: (.68,.59,.53,.50,.47,.43,.40,.36,.32,.30,.27,.18,.15),
    36: (.69,.59,.54,.51,.47,.43,.40,.37,.33,.30,.28,.19,.16),
    40: (.70,.60,.55,.52,.48,.44,.41,.37,.33,.31,.28,.19,.16),
    100: (.77,.69,.64,.60,.56,.52,.49,.45,.40,.37,.34,.23,.20),
    500: (.95,.92,.89,.88,.86,.83,.81,.77,.73,.70,.66,.50,.44),
    1000: (.99,.98,.97,.97,.96,.95,.94,.93,.91,.90,.88,.77,.71),
}


def positive(value, label):
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{label}: требуется положительное конечное число")


@dataclass(frozen=True)
class KsTableCell:
    fixtures_count: int
    receiving_length_m: float
    ks: float


@dataclass(frozen=True)
class KsSelection:
    value: float
    method: str
    n_bounds: tuple[int, int]
    length_bounds_m: tuple[float, float]
    cells: tuple[KsTableCell, ...]

    @property
    def note(self) -> str:
        if self.method == "table":
            return "Ks взят из точной ячейки таблицы 5.1."
        axis = {"linear_n": "N", "linear_l": "L", "bilinear": "N и L"}[self.method]
        cells = "; ".join(f"N={c.fixtures_count}, L={c.receiving_length_m:g} м: Ks={c.ks:g}"
                          for c in self.cells)
        return (f"Ks определён линейной интерполяцией по {axis}; опорные ячейки: {cells}. "
                "Интерполяция — принятый инженерный способ обработки таблицы, "
                "не отдельное предписание СП; исходные N и L не округлялись.")


def _bounds(value, nodes, label):
    if not nodes[0] <= value <= nodes[-1]:
        raise ValueError(f"{label} вне таблицы 5.1 ({nodes[0]}–{nodes[-1]}): "
                         "экстраполяция и округление к границе не допускаются. "
                         "Нужен отдельный обоснованный расчёт участка.")
    index = bisect_left(nodes, value)
    if nodes[index] == value:
        return nodes[index], nodes[index]
    return nodes[index - 1], nodes[index]


def select_ks(fixtures_count: int, receiving_length_m: float) -> KsSelection:
    """Exact cells, one-axis linear or two-axis bilinear interpolation.

    Use actual (nonuniform) axis intervals, never grid indices or rounded inputs.
    Degenerate intervals return the published value without interpolation.
    """
    if type(fixtures_count) is not int or fixtures_count <= 0:
        raise ValueError("N: требуется целое положительное число подключённых приборов")
    positive(receiving_length_m, "L по таблице 5.1")
    n0, n1 = _bounds(fixtures_count, tuple(sorted(KS_ROWS)), "N")
    l0, l1 = _bounds(receiving_length_m, LENGTHS_M, "L")
    j0, j1 = LENGTHS_M.index(l0), LENGTHS_M.index(l1)

    def at_length(n):
        a, b = KS_ROWS[n][j0], KS_ROWS[n][j1]
        return a if l0 == l1 else a + (b - a) * (receiving_length_m - l0) / (l1 - l0)

    lower, upper = at_length(n0), at_length(n1)
    value = lower if n0 == n1 else lower + (upper - lower) * (fixtures_count - n0) / (n1 - n0)
    method = ("table" if n0 == n1 and l0 == l1 else "linear_l" if n0 == n1
              else "linear_n" if l0 == l1 else "bilinear")
    cells = tuple(KsTableCell(n, length, KS_ROWS[n][LENGTHS_M.index(length)])
                  for n in dict.fromkeys((n0, n1)) for length in dict.fromkeys((l0, l1)))
    return KsSelection(value, method, (n0, n1), (l0, l1), cells)


@dataclass(frozen=True)
class HorizontalSewageResult:
    q_hour_max_m3h: float
    fixtures_count: int
    receiving_length_m: float
    fixture_max_lps: float
    ks: float
    q_sewage_lps: float
    ks_selection: KsSelection

    @property
    def note(self):
        return (f"СП 30, п. 5.7, формула (7): q_sL = {self.q_hour_max_m3h:g}/3,6 + "
                f"{self.ks:g}×{self.fixture_max_lps:g} = {self.q_sewage_lps:.3f} л/с; "
                f"таблица 5.1: N={self.fixtures_count}, L={self.receiving_length_m:g} м. "
                f"{self.ks_selection.note} "
                "L — от последнего стояка до ближайшего следующего присоединения "
                "либо, при его отсутствии, до ближайшего канализационного колодца.")


def calculate_horizontal_sewage(q_hour_max_m3h, fixtures_count, receiving_length_m,
                               fixture_max_lps) -> HorizontalSewageResult:
    for value, label in ((q_hour_max_m3h, "Максимальный часовой расход участка"),
                         (receiving_length_m, "L по таблице 5.1"),
                         (fixture_max_lps, "q0s по таблице А.1")):
        positive(value, label)
    selection = select_ks(fixtures_count, receiving_length_m)
    ks = selection.value
    q = q_hour_max_m3h / 3.6 + ks * fixture_max_lps
    positive(q, "Результат q_sL")
    # No intermediate rounding; existing hydraulics receive the full result.
    return HorizontalSewageResult(q_hour_max_m3h, fixtures_count, receiving_length_m,
                                 fixture_max_lps, ks, q, selection)


def resolve_horizontal_flow(*, design_flow_lps=None, flow_source="", q_hour_max_m3h=None,
                            fixtures_count=None, receiving_length_m=None, fixture_max_lps=None):
    """Return (flow, evidence, note). Partial/conflicting/old inputs fail closed."""
    auto = (q_hour_max_m3h, fixtures_count, receiving_length_m, fixture_max_lps)
    if design_flow_lps is not None:
        if any(v is not None for v in auto):
            return None, None, "Одновременно сохранены ручной расход и исходные формулы (7); выберите один способ."
        try:
            positive(design_flow_lps, "Ручной расход участка")
        except ValueError as exc:
            return None, None, str(exc)
        if not isinstance(flow_source, str) or not flow_source.strip():
            return None, None, "Для ручного расхода горизонтального участка нужно основание расчёта, не расход стояка."
        return design_flow_lps, None, f"Явно заданный расход горизонтального участка: {flow_source}."
    missing = [label for value, label in zip(auto, ("максимальный часовой расход участка",
        "число подключённых приборов N", "L по примечанию таблицы 5.1", "q0s по таблице А.1")) if value is None]
    if missing:
        return None, None, "Расход горизонтального участка по п. 5.7: нужны " + ", ".join(missing) + "."
    try:
        result = calculate_horizontal_sewage(*auto)
    except (ValueError, ArithmeticError) as exc:
        return None, None, str(exc)
    return result.q_sewage_lps, result, result.note
