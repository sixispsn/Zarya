# -*- coding: utf-8 -*-
"""
app/calc/fire_design.py — оркестратор расстановки ПК (сшивка слоёв 1-2-3).

Единая точка входа: из нормативного контекста помещения получить готовую
расстановку пожарных кранов с проверкой покрытия — без ручной сборки JetParams
и FireCabinetNormative.

Цепочка (по архитектуре Антона):
    FireNormativeContext
        → resolve_fire_normative      (слой 1: Rk по п.7.15/форм.3, кратность п.6.2.2)
        → layout_rectangular_room     (слой 3: шаг L по форм.(1), расстановка)
          └ точки берутся из placement_rules (слой 2: где можно ставить)
        → assign_risers               (эвристика стадии П)
        → check_required_jet_coverage (отчёт покрытия)

Что НЕ делается автоматически (осознанные заглушки):
  • число ПК (required_jets) — через override в контексте, пока табл. 7.1 не
    закодирована (fire_normative);
  • riser_id — эвристика от стены; в целевой Заре из трассировки сети В2;
  • геометрия — прямоугольная (SP_RECTANGULAR).

Если нормативный слой пометил manual_review_required (напр. 2 струи в не-коридорном
пространстве, где СП не нормирует разные стояки) — это пробрасывается в результат.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.calc.fire_normative import (
    FireNormativeContext, ResolvedFireNormative, resolve_fire_normative,
)
from app.calc.fire_layout import (
    RectangularRoom, FireCabinetLayoutSummary, design_fire_cabinets_for_room,
)
from app.calc.fire_models import FireCabinetNormative


def build_scenario_filter(normative: FireCabinetNormative):
    """Собирает предикат допустимости набора ПК для гидравлики из нормативных
    правил (glue-слой). Гидравлика применяет его как чёрный ящик, не зная политики.

    Сейчас реализовано правило «разные стояки» (п. 6.2.2): при
    require_different_risers все ПК набора должны иметь различные riser_id.

    Строгий режим (по решению Антона): если require_different_risers=True, а у
    какого-то ПК riser_id не заполнен — набор НЕДОПУСТИМ (иначе солвер соврёт).
    Сюда же позже добавляются другие ограничения (одно помещение, разные ветви,
    покрытие зоны) — гидравлики это не касается.
    """
    def _filter(cabs) -> bool:
        if len(cabs) <= 1:
            return True
        if normative.require_different_risers:
            risers = [c.riser_id for c in cabs]
            if any(r is None for r in risers):
                return False  # строгий режим: нет riser_id → недопустимо
            return len(set(risers)) == len(risers)
        return True
    return _filter


@dataclass
class FireDesignResult:
    """Итог сквозной расстановки ПК от нормативного контекста."""
    resolved_normative: ResolvedFireNormative
    layout: Optional[FireCabinetLayoutSummary]
    pk_total: int
    coverage_ok: bool
    manual_review_required: bool
    notes: List[str] = field(default_factory=list)


def design_fire_cabinets_from_context(
    ctx: FireNormativeContext,
    room: RectangularRoom,
    *,
    control_step_m: float = 1.0,
    edge_offset_m: float = 1.0,
    auto_pattern: bool = True,
) -> FireDesignResult:
    """Сквозная расстановка ПК: контекст + геометрия помещения → результат.

    ctx: нормативный контекст (тип здания/пространства, высота, ширина, режим,
        число струй через override пока табл. 7.1 не закодирована).
    room: прямоугольное помещение (длина/ширина/высота).

    Нормативные Rk и кратность берутся из ctx (слой 1), не задаются в layout руками.
    Возвращает расстановку, число ПК, флаг покрытия и проброшенный manual_review.
    """
    resolved = resolve_fire_normative(ctx)

    try:
        layout = design_fire_cabinets_for_room(
            room=room,
            jet=resolved.jet_params,
            normative=resolved.cabinet_normative,
            control_step_m=control_step_m,
            edge_offset_m=edge_offset_m,
            auto_pattern=auto_pattern,
        )
    except ValueError as e:
        # напр. Rk не добивает до верха помещения (H−1,35 > Rk) или ширина больше
        # досягаемости — расстановка по СП невозможна с этим Rk/геометрией.
        return FireDesignResult(
            resolved_normative=resolved,
            layout=None,
            pk_total=0,
            coverage_ok=False,
            manual_review_required=True,
            notes=list(resolved.notes) + [
                f"РАССТАНОВКА НЕВОЗМОЖНА по СП с текущими параметрами: {e}. "
                "Проверьте Rk (возможно нужен расчёт по формуле (3) п. 7.16 при "
                "большем давлении), высоту/ширину помещения или схему размещения."],
        )

    notes = list(resolved.notes)
    notes.extend(layout.placement_result.notes)
    if resolved.jet_multiplicity.manual_review_required:
        notes.append("ТРЕБУЕТСЯ ручная проверка: нормативный слой не смог однозначно "
                     "определить требование разных стояков для этого пространства.")
    if not layout.coverage_result.ok:
        notes.append(f"ПОКРЫТИЕ НЕ ОБЕСПЕЧЕНО: непокрытых точек "
                     f"{len(layout.coverage_result.insufficient_points)}.")

    return FireDesignResult(
        resolved_normative=resolved,
        layout=layout,
        pk_total=len(layout.placement_result.placements),
        coverage_ok=layout.coverage_result.ok,
        manual_review_required=resolved.jet_multiplicity.manual_review_required,
        notes=notes,
    )


def _example() -> None:
    from app.calc.fire_normative import FireBuildingKind, FireSpaceKind
    from app.calc.fire_models import PlacementMode

    # коридор общественного здания >10 м, 2 струи → разные стояки
    ctx = FireNormativeContext(
        building_kind=FireBuildingKind.PUBLIC, space_kind=FireSpaceKind.CORRIDOR,
        room_height_m=3.3, room_width_m=12.0, building_height_m=40.0,
        placement_mode=PlacementMode.TWO_OPPOSITE_SIDES, required_jets_override=2)
    room = RectangularRoom("corridor_1", length_m=48.0, width_m=12.0, height_m=3.3)

    res = design_fire_cabinets_from_context(ctx, room)
    print(f"Rk = {res.resolved_normative.jet_params.compact_jet_radius_m} м")
    print(f"струй = {res.resolved_normative.cabinet_normative.required_jets}, "
          f"разные стояки = {res.resolved_normative.cabinet_normative.require_different_risers}")
    print(f"шаг L = {res.layout.placement_result.spacing_L_m:.2f} м")
    print(f"ПК = {res.pk_total}, покрытие = {'OK' if res.coverage_ok else 'НЕ ОК'}, "
          f"ручная проверка = {res.manual_review_required}")


if __name__ == "__main__":
    _example()
