"""Restrictive read-only projection of cached findings after preview file loss.

No project construction, solver, new normative decision or release approval.
The saved report stays intact; this view only withdraws document evidence.
"""
from copy import deepcopy
from dataclasses import fields

from app.quality_gates import QualityFinding, QualityGate, QualityState, ReleaseQualityReport
from app.intake.studio_readiness import section_readiness
from app.pz.artifact_readiness import COMMISSION_DOCUMENT_ARTIFACTS


def restrict_preview_calculation(calculation, lost_labels, missing_names, *, collection="preview"):
    result = deepcopy(calculation)
    lost_facts = {f"artifact.{label}" for label in lost_labels}
    detail = "Файлы предпросмотра отсутствуют или пусты: " + ", ".join(missing_names)
    action = "Повторно сформировать предпросмотр по текущим исходным данным"
    package = collection == "package"
    if package:
        detail = "Сохранённый комплект недоступен: " + ", ".join(missing_names)
        action = "Проверить сохранённые файлы выпуска; исходный снимок не изменён"
    finding_fields = {field.name for field in fields(QualityFinding)}
    gates = []
    affected = []
    for gate in result.get("quality", {}).get("gates", []):
        rows = []
        for saved in gate["findings"]:
            row = QualityFinding(**{
                **{key: value for key, value in saved.items() if key in finding_fields},
                "state": QualityState(saved["state"]),
            })
            # fact_ids are the existing document dependency graph, not title matching.
            dependent = lost_facts.intersection(row.fact_ids) or (
                row.source == "commission" and
                set(COMMISSION_DOCUMENT_ARTIFACTS.get(row.code, ())).intersection(lost_labels))
            if dependent and row.state != QualityState.BLOCKED:
                row = QualityFinding(**{
                    **{key: getattr(row, key) for key in finding_fields},
                    "state": QualityState.BLOCKED, "detail": detail, "action": action,
                })
                if row.source == "normative_audit":
                    affected.append(row)
            if row.source == "quality_gates":
                row = QualityFinding(row.code, row.title, detail, action, row.reference,
                                     QualityState.BLOCKED, row.source)
            rows.append(row)
        state = (QualityState.BLOCKED if any(r.state == QualityState.BLOCKED for r in rows)
                 else QualityState(gate["state"]))
        gates.append(QualityGate(gate["gate_id"], gate["title"], gate["description"], state, tuple(rows)))
    # This technical guard also covers PDFs without a dedicated normative row.
    guard = QualityFinding("PACKAGE-FILES" if package else "PREVIEW-FILES",
                           "Файлы сохранённого комплекта недоступны" if package else "Файлы текущего предпросмотра недоступны",
                           detail, action, "Контроль доступности файлов Zarya",
                           QualityState.BLOCKED, "package_files" if package else "preview_files",
                           fact_ids=tuple(sorted(lost_facts)))
    gates.append(QualityGate("package_files" if package else "preview_files",
                            "Доступность комплекта" if package else "Доступность предпросмотра",
                            "Проверка файлов без пересчёта проекта", QualityState.BLOCKED, (guard,)))
    result["quality"] = ReleaseQualityReport(tuple(gates), QualityState.BLOCKED).to_dict()
    result["can_release"] = False
    result["review_sections"] = section_readiness(result["quality"])
    blockers = result.setdefault("gost_blockers", [])
    for row in affected:
        if not any(b["rule_id"] == row.code for b in blockers):
            blockers.append(dict(rule_id=row.code, title=row.title, evidence=row.detail,
                                 reference=row.reference, status="missing", blocks_release=True,
                                 systems=list(row.systems), fact_ids=list(row.fact_ids)))
    return result
