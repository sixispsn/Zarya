"""Несохраняемый предпросмотр влияния изменений исходных данных.

Предпросмотр не содержит собственных инженерных формул. Изменённое намерение
повторно проходит ProjectBuilder и штатный design_ios2 в расчётном режиме без
рендеринга документов. Затем сравниваются уже полученные результаты Project.
"""
from __future__ import annotations

import copy
import math
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional

from app.data.sp30_tables import get_consumer_norm
from app.intake.project_builder import RequestValidationError, build_project
from app.intake.request_dto import IOS2Request, SourceDataRequest
from app.pz.commission import CommissionReport
from app.pz.ios2_orchestrator import design_ios2
from app.pz.project import Project
from app.pz.rules import calc_required_head
from app.schemas.impact import ImpactPreviewInput


class ImpactValidationError(ValueError):
    """Изменение нельзя безопасно пропустить через расчётный конвейер."""


@dataclass(frozen=True)
class InputChange:
    id: str
    label: str
    before: str
    after: str
    unit: str = ""


@dataclass(frozen=True)
class ResultDelta:
    id: str
    system: str
    label: str
    before: str
    after: str
    unit: str
    changed: bool
    proof_id: str
    detail: str
    documents: list[str] = field(default_factory=list)


@dataclass
class ImpactPreview:
    baseline_fingerprint: str
    preview_fingerprint: str
    input_changes: list[InputChange]
    deltas: list[ResultDelta]
    affected_documents: list[str]
    warnings: list[str]
    calculation_status: str = "Расчёт выполнен, проект не сохранён"

    @property
    def changed_count(self) -> int:
        return sum(item.changed for item in self.deltas)

    @property
    def unchanged_count(self) -> int:
        return len(self.deltas) - self.changed_count

    def to_dict(self) -> dict:
        return {
            "baseline_fingerprint": self.baseline_fingerprint,
            "preview_fingerprint": self.preview_fingerprint,
            "calculation_status": self.calculation_status,
            "summary": {
                "inputs_changed": len(self.input_changes),
                "results_changed": self.changed_count,
                "results_unchanged": self.unchanged_count,
                "documents_affected": len(self.affected_documents),
            },
            "input_changes": [vars(item) for item in self.input_changes],
            "deltas": [vars(item) for item in self.deltas],
            "affected_documents": self.affected_documents,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class _Metric:
    raw: Any
    display: str
    unit: str
    detail: str
    documents: list[str]


_DOCUMENT_ORDER = (
    "Пояснительная записка",
    "Расчёты В1",
    "Баланс ВиВ",
    "Подбор насосов",
    "Спецификация",
    "Схема",
    "Гидравлический расчёт В2",
    "Паспорт проекта",
)


def _ru(value: Optional[float], precision: int = 2) -> str:
    if value is None:
        return "не определено"
    return f"{value:.{precision}f}".replace(".", ",")


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), abs_tol=0.0005)
    return left == right


def _cold_meter(project: Project):
    rows = project.meters.rows or []
    for row in rows:
        if "ввод" in row.label.lower():
            return row
    for row in rows:
        if "хвс" in row.label.lower() or "холодн" in row.label.lower():
            return row
    return rows[0] if rows else None


def _head(project: Project):
    meter = _cold_meter(project)
    return calc_required_head(
        project.source,
        h_vod_m=(meter.h_a if meter is not None else project.source.h_vod_m),
    )


def _meter_metric(project: Project) -> _Metric:
    meter = _cold_meter(project)
    if meter is None:
        return _Metric(
            None, "не подобран", "",
            "Расчётный узел отсутствует.",
            ["Расчёты В1", "Пояснительная записка", "Спецификация"],
        )
    return _Metric(
        (meter.dn, meter.type_label, meter.need_bypass, meter.h_a),
        f"DN{meter.dn} · h={_ru(meter.h_a, 3)} м",
        meter.type_label,
        (
            f"h={_ru(meter.h_a, 3)} м; "
            f"обводная линия {'требуется' if meter.need_bypass else 'не требуется'}."
        ),
        ["Расчёты В1", "Пояснительная записка", "Спецификация"],
    )


def _diameter_metric(project: Project) -> _Metric:
    stage_p = getattr(project, "v1_stage_p_result", None)
    if stage_p and getattr(stage_p, "rows", None):
        row = stage_p.rows[0]
        return _Metric(
            (
                row.dn, row.outer_mm, row.wall_mm, row.inner_mm,
                row.flow_lps, row.velocity_mps, row.velocity_ok,
            ),
            f"DN{row.dn} · v={_ru(row.velocity_mps, 3)} м/с",
            f"{row.outer_mm:g}×{row.wall_mm:g} мм",
            (
                f"Dвн={row.inner_mm:g} мм; v={_ru(row.velocity_mps, 3)} м/с; "
                f"скорость {'соответствует' if row.velocity_ok else 'не соответствует'}."
            ),
            ["Расчёты В1", "Спецификация"],
        )
    hydraulic = getattr(project, "v1_hydraulic_result", None)
    sections = getattr(hydraulic, "sections", None)
    if sections:
        signature = tuple(
            (
                getattr(row, "section_id", ""),
                getattr(row, "inner_diameter_mm", None),
            )
            for row in sections
        )
        return _Metric(
            signature,
            f"{len(sections)} участков",
            "расчётная топология",
            "Сечения определены штатной гидравликой В1.",
            ["Расчёты В1", "Спецификация"],
        )
    return _Metric(
        None, "не определено", "",
        "Для точных сечений нужна расчётная схема.",
        ["Расчёты В1", "Спецификация"],
    )


def _pump_metric(project: Project) -> _Metric:
    head = _head(project)
    pump = project.pumps
    if head.pump_needed is False:
        return _Metric(
            ("not_required",),
            "не требуется",
            "",
            (
                f"Hтр={_ru(head.h_required_m, 2)} м не превышает "
                f"Hгар={_ru(head.h_guaranteed_m, 2)} м."
            ),
            ["Пояснительная записка", "Подбор насосов", "Схема", "Спецификация"],
        )
    if head.pump_needed is None:
        return _Metric(
            ("undetermined",),
            "не определено",
            "",
            "Не хватает Hтр или Hгар.",
            ["Пояснительная записка", "Подбор насосов"],
        )
    if not pump.model:
        return _Metric(
            ("selection_required", pump.q_design_m3h, pump.h_design_m),
            "требуется подбор",
            "",
            "Каталог не дал подтверждённого кандидата.",
            ["Пояснительная записка", "Подбор насосов", "Схема", "Спецификация"],
        )
    return _Metric(
        (pump.model, pump.wp_q, pump.wp_h),
        (
            f"{pump.model} · Q{_ru(pump.wp_q, 1)} / "
            f"H{_ru(pump.wp_h, 1)}"
        ),
        "",
        f"Рабочая точка Q={_ru(pump.wp_q, 2)} м³/ч; H={_ru(pump.wp_h, 1)} м.",
        ["Пояснительная записка", "Подбор насосов", "Схема", "Спецификация"],
    )


def _fire_metric(project: Project) -> _Metric:
    fire = project.fire
    if not fire.required:
        return _Metric(
            (False, 0, 0.0),
            "не требуется",
            "",
            fire.normative_note,
            [
                "Пояснительная записка", "Схема", "Спецификация",
                "Гидравлический расчёт В2", "Подбор насосов",
            ],
        )
    return _Metric(
        (True, fire.streams, fire.q_per_stream, fire.q_total),
        _ru(fire.q_total, 1),
        "л/с",
        (
            f"{fire.streams} струй × {_ru(fire.q_per_stream, 1)} л/с; "
            f"{fire.normative_note}"
        ),
        [
            "Пояснительная записка", "Схема", "Спецификация",
            "Гидравлический расчёт В2", "Подбор насосов",
        ],
    )


def _normative_metric(project: Project) -> _Metric:
    normative = project.normative
    codes = []
    if normative.sp54_applicable:
        codes.append("СП 54")
    if normative.sp118_applicable:
        codes.append("СП 118")
    if normative.sp253_applicable:
        codes.append("СП 253")
    display = " + ".join(codes) if codes else "базовый профиль"
    raw = (
        normative.sp54_applicable,
        normative.sp118_applicable,
        normative.sp253_applicable,
        normative.mixed_use,
        normative.separate_v1_v2_required,
    )
    decisions = []
    if normative.separate_v1_v2_required:
        decisions.append("раздельные В1/В2")
    if normative.frequency_drive_required:
        decisions.append("частотные насосы")
    if normative.separate_k1_required:
        decisions.append("раздельные К1")
    detail = "; ".join(decisions) if decisions else "Дополнительные высотные меры не требуются."
    return _Metric(
        raw, display, "", detail,
        ["Пояснительная записка", "Паспорт проекта", "Схема", "Спецификация"],
    )


def _metrics(project: Project) -> dict[str, _Metric]:
    head = _head(project)
    return {
        "q-day": _Metric(
            project.flows.q_day_tot,
            _ru(project.flows.q_day_tot, 1),
            "м³/сут",
            "Суточная сумма по группам потребителей.",
            ["Пояснительная записка", "Расчёты В1", "Баланс ВиВ"],
        ),
        "q-sec-cold": _Metric(
            project.flows.q_sec_c,
            _ru(project.flows.q_sec_c, 3),
            "л/с",
            "Вероятностный расход ХВС по штатному calcBlock.",
            ["Пояснительная записка", "Расчёты В1", "Подбор насосов"],
        ),
        "q-sec-hot": _Metric(
            project.flows.q_sec_h,
            _ru(project.flows.q_sec_h, 3),
            "л/с",
            "Вероятностный расход ГВС по штатному calcBlock.",
            ["Пояснительная записка", "Расчёты В1", "Баланс ВиВ"],
        ),
        "sewage": _Metric(
            project.flows.sewage_l_per_s,
            _ru(project.flows.sewage_l_per_s, 3),
            "л/с",
            "Расход К1 по формуле (5) СП 30 с заданным q₀s.",
            [
                "Пояснительная записка",
                "Расчёты К1/К2",
                "Схема К1/К2",
                "Баланс ВиВ",
            ],
        ),
        "meter": _meter_metric(project),
        "diameter": _diameter_metric(project),
        "head": _Metric(
            (head.h_required_m, head.h_guaranteed_m, head.pump_needed),
            _ru(head.h_required_m, 2),
            "м вод. ст.",
            (
                f"Hгар={_ru(head.h_guaranteed_m, 2)} м; "
                f"Hпр={_ru(head.h_pr_m, 1)} м."
            ),
            ["Пояснительная записка", "Расчёты В1", "Подбор насосов"],
        ),
        "pump": _pump_metric(project),
        "fire": _fire_metric(project),
        "normative": _normative_metric(project),
    }


_METRIC_META = {
    "q-day": ("В1", "Суточный расход", "v1-q-day"),
    "q-sec-cold": ("В1", "Секундный расход ХВС", "v1-q-sec"),
    "q-sec-hot": ("Т3", "Секундный расход ГВС", "v1-q-sec"),
    "sewage": ("К1", "Расход хозяйственно-бытовых стоков", "k1-flow"),
    "meter": ("В1", "Водомерный узел", "v1-meter"),
    "diameter": ("В1", "Сечение ввода", "v1-diameter"),
    "head": ("В1", "Требуемый напор", "v1-head"),
    "pump": ("В1", "Повысительная установка", "v1-pump"),
    "fire": ("В2", "Необходимость и расход ВПВ", "v2-requirement"),
    "normative": ("Нормы", "Нормативный профиль", "high-rise-systems"),
}


def impact_form_context(request: IOS2Request) -> dict:
    groups = []
    for index, group in enumerate(request.consumers):
        norm = get_consumer_norm(group.code)
        groups.append({
            "index": index,
            "name": group.name or (norm.label if norm else group.code),
            "code": group.code,
            "count": group.count,
            "unit": norm.unit if norm else "ед.",
        })
    source = request.source_data
    return {
        "consumer_groups": groups,
        "consumer_editable": request.v1_network is None,
        "floors": request.floors,
        "building_height_m": request.building_height_m,
        "fire_height_m": request.fire_height_m,
        "guaranteed_head_m": (
            source.guaranteed_head_m if source is not None else None
        ),
        "fire_mode": request.fire_mode,
    }


def _format_input(value: Any, precision: int = 1) -> str:
    if isinstance(value, float):
        return _ru(value, precision)
    if value is None:
        return "не задано"
    return str(value)


def _apply_changes(
    request: IOS2Request,
    data: ImpactPreviewInput,
) -> tuple[IOS2Request, list[InputChange]]:
    proposed = copy.deepcopy(request)
    changes: list[InputChange] = []

    if data.consumer_counts is not None:
        if len(data.consumer_counts) != len(proposed.consumers):
            raise ImpactValidationError(
                "Число групп в предпросмотре не совпадает с исходным проектом."
            )
        if any(count <= 0 for count in data.consumer_counts):
            raise ImpactValidationError(
                "Количество потребителей в каждой группе должно быть больше нуля."
            )
        if proposed.v1_network is not None and any(
            group.count != count
            for group, count in zip(proposed.consumers, data.consumer_counts)
        ):
            raise ImpactValidationError(
                "В проекте расходы заданы топологией В1. Изменяйте потребителей "
                "в узлах расчётной схемы, а не в сводном предпросмотре."
            )
        for index, (group, count) in enumerate(
            zip(proposed.consumers, data.consumer_counts)
        ):
            if group.count != count:
                norm = get_consumer_norm(group.code)
                changes.append(InputChange(
                    f"consumer-{index}",
                    group.name or (norm.label if norm else group.code),
                    str(group.count),
                    str(count),
                    norm.unit if norm else "ед.",
                ))
                group.count = count

    scalar_fields = (
        ("floors", "Этажность", "эт.", 0),
        ("building_height_m", "Высота здания", "м", 1),
        ("fire_height_m", "Пожарно-техническая высота", "м", 1),
    )
    for field_name, label, unit, precision in scalar_fields:
        value = getattr(data, field_name)
        if value is None:
            continue
        before = getattr(proposed, field_name)
        if not _same(before, value):
            changes.append(InputChange(
                field_name, label,
                _format_input(before, precision),
                _format_input(value, precision),
                unit,
            ))
            setattr(proposed, field_name, value)

    if data.guaranteed_head_m is not None:
        if proposed.source_data is None:
            proposed.source_data = SourceDataRequest()
        before = proposed.source_data.guaranteed_head_m
        if not _same(before, data.guaranteed_head_m):
            changes.append(InputChange(
                "guaranteed_head_m", "Гарантированный напор по ТУ",
                _format_input(before, 1),
                _format_input(data.guaranteed_head_m, 1),
                "м",
            ))
            proposed.source_data.guaranteed_head_m = data.guaranteed_head_m

    problems = proposed.validate()
    if problems:
        raise ImpactValidationError("; ".join(problems))
    return proposed, changes


def calculate_impact_preview(
    request: IOS2Request,
    baseline_project: Project,
    baseline_report: CommissionReport,
    data: ImpactPreviewInput,
) -> ImpactPreview:
    """Пересчитать предложенный вариант и сравнить с текущим без сохранения."""
    proposed_request, input_changes = _apply_changes(request, data)
    try:
        proposed_project = build_project(proposed_request)
    except RequestValidationError as exc:
        raise ImpactValidationError("; ".join(exc.problems)) from exc
    except ValueError as exc:
        raise ImpactValidationError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="zarya-impact-") as output_dir:
        proposed_bundle = design_ios2(
            proposed_project,
            output_dir=output_dir,
            render_documents=False,
        )

    before_metrics = _metrics(baseline_project)
    after_metrics = _metrics(proposed_bundle.project)
    deltas = []
    affected = set()
    for metric_id, before in before_metrics.items():
        after = after_metrics[metric_id]
        changed = not _same(before.raw, after.raw)
        if changed:
            affected.update(after.documents)
        system, label, proof_id = _METRIC_META[metric_id]
        deltas.append(ResultDelta(
            metric_id,
            system,
            label,
            before.display,
            after.display,
            after.unit or before.unit,
            changed,
            proof_id,
            after.detail,
            after.documents,
        ))

    ordered_documents = [
        name for name in _DOCUMENT_ORDER if name in affected
    ]
    proposed_report = proposed_bundle.commission_report
    warnings = list(dict.fromkeys(proposed_bundle.warnings))[:8]
    if any(
        change.id in {"floors", "building_height_m"}
        for change in input_changes
    ):
        warnings.insert(
            0,
            "Hgeom и отметки диктующего прибора оставлены исходными: высота "
            "здания не подменяет геодезические отметки. При принятии изменения "
            "уточните их в исходных данных напора.",
        )
    if any(
        change.id in {"floors", "building_height_m", "fire_height_m"}
        for change in input_changes
    ) and request.network is not None:
        warnings.insert(
            0,
            "Геометрия существующей сети В2 оставлена исходной. При принятии "
            "изменения требуется актуализировать отметки и длины сети.",
        )
    return ImpactPreview(
        baseline_fingerprint=baseline_report.project_fingerprint,
        preview_fingerprint=proposed_report.project_fingerprint,
        input_changes=input_changes,
        deltas=deltas,
        affected_documents=ordered_documents,
        warnings=warnings,
    )
