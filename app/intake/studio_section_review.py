"""Review of a particular representative PDF, never engineering certification.

No paper geometry, review checkbox or file-presence flag changes calculations,
the measured network, quantities, K-GOST checks or permission to release.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from app.intake.pilot_objects import calculation_stamp, checksum
from app.intake.studio_intake import IntakeError, accepted_values
from app.intake.studio_section import section_fan, section_main, section_readiness
from app.pz.section_fan import resolve_section_fan

REVIEW_VERSION = "representative-pdf-review-2"
NOTICE = ("Сохраняется только просмотр компоновки конкретного PDF. Это не допуск "
          "к выпуску, не проверка всей сети и не основание для подсчёта длин труб.")


def content_checklist(values: dict) -> list[dict]:
    """Separate already available inputs from actual remaining drawing work.

    GOST R 21.620-2023 5.2.2.2/5.2.2.4; no requirement for a measured R-stage
    registry is introduced. Supplied values are not called verified solutions.
    """
    status = section_readiness(values)
    rows = []
    for system in ("k1", "k2") if status["drainage"] == "internal" else ("k1",):
        data = section_main(values, system)
        rows.append(dict(code=system, title=system.upper().replace("K", "К") + " · магистраль и выпуск",
                         state="needs_input" if data.missing else "supplied",
                         note=("Уточнить: " + ", ".join(data.missing)) if data.missing else
                         "DN, уклон, относительная отметка выпуска, приёмник и основание указаны. Требуется проверка решения."))
    if status["ready"]:
        fan = resolve_section_fan(values["roof_type"], values["floors"], values["floor_height_m"], section_fan(values))
        rows.append(dict(code="fan", title="Фановая вентиляция",
                         state="needs_input" if fan.kind == "pending" else "supplied", note=fan.notice))
    datum_missing = values.get("section_zero_absolute_m") is None or not values.get("section_zero_source_ref", "").strip()
    rows.append(dict(code="datum", title="Абсолютная привязка выпусков",
                     state="needs_input" if datum_missing else "supplied",
                     note="Укажите абсолютную отметку 0,000 и её основание в «Здание → Привязка отметок»." if datum_missing else
                     "Абсолютные лотки рассчитываются из заданного нуля и относительных лотков. Условия наружной сети этим не проверены."))
    rows.extend([
        dict(code="ar", title="Помещения и привязка к АР", state="drawing_work",
             note="Пока показаны типовые кухня и санузел без номеров по экспликации. Нужны привязка помещений и проверка транзитных помещений, пожарных преград и деформационных швов по АР."),
        dict(code="levels", title="Полнота отметок на листе", state="drawing_work",
             note="Абсолютные выпуски и отметки начала магистралей передаются на лист из исходных. Ещё нужны проектные отметки поэтажных подключений и нижнего прибора; их нельзя получить из условного масштаба картинки."),
        dict(code="special", title="Особые узлы и обслуживание", state="manual_check",
             note="Сверить с объектом: доступ к ревизиям и прочисткам, утепление, насосы, клапаны и автоматика — если применимы. Типовой разрез не подтверждает обслуживание всех реальных ветвей."),
    ])
    return rows


def review_state(draft: dict, folder: Path, handoff_version: str) -> dict | None:
    calculation = draft.get("project_calculation") or {}
    scheme = calculation.get("sewer_scheme") or {}
    record = draft.get("section_review")
    if draft.get("study") or (scheme.get("presentation") != "representative" and not record):
        return None
    result = dict(state="needs_pdf", can_record=False, current=None,
                  record={key: record.get(key) for key in ("reviewer", "architecture_ref", "reviewed_at")}
                  if isinstance(record, dict) else None,
                  notice=NOTICE, release_ready=False, takeoff_eligible=False,
                  checklist=content_checklist(accepted_values(draft)))
    saved = draft.get("preview") or {}
    preview_id = saved.get("id", "")
    if (scheme.get("presentation") == "representative"
            and calculation.get("handoff_version") == handoff_version
            and saved.get("handoff_version") == handoff_version
            and saved.get("stamp") == calculation_stamp(draft)
            and re.fullmatch(r"[a-f0-9]{32}", preview_id)):
        docs = [d for d in saved.get("documents", []) if d.get("kind") == "wastewater_scheme_pdf"]
        if len(docs) == 1:
            name = docs[0].get("name", "")
            path = folder / "previews" / preview_id / name
            # No arbitrary path or symlink may become evidence for another user.
            if (name and Path(name).name == name and path.resolve().is_relative_to(folder.resolve())
                    and not path.is_symlink() and path.is_file()):
                data = path.read_bytes()
                if data.startswith(b"%PDF-"):
                    current = dict(preview_id=preview_id, filename=name,
                                   pdf_sha256=hashlib.sha256(data).hexdigest(),
                                   source_sha256=checksum(dict(stamp=calculation_stamp(draft),
                                       documents=draft.get("documents", []))),
                                   handoff_version=handoff_version, review_version=REVIEW_VERSION)
                    current["fingerprint"] = checksum(current)
                    result.update(state="unreviewed", can_record=True, current=current)
    if record:
        result["state"] = ("reviewed" if result["current"] and
                           record.get("fingerprint") == result["current"]["fingerprint"] else "stale")
    return result


def record_review(draft: dict, folder: Path, handoff_version: str, *, fingerprint: str,
                  reviewer: str, architecture_ref: str, confirm: bool, actor_id: str) -> None:
    if not confirm or not reviewer.strip() or not architecture_ref.strip():
        raise IntakeError("Укажите проверившего, листы АР и подтвердите просмотр PDF.")
    status = review_state(draft, folder, handoff_version)
    if not status or not status["can_record"]:
        raise IntakeError("Сначала сформируйте текущий PDF характерного разреза ИОС3.")
    if status["current"]["fingerprint"] != fingerprint:
        raise IntakeError("Исходные или PDF изменились. Откройте текущую схему и проверьте её заново.")
    draft["section_review"] = dict(**status["current"], reviewer=reviewer.strip(),
        architecture_ref=architecture_ref.strip(), actor_id=actor_id,
        reviewed_at=datetime.now(timezone.utc).isoformat(), scope="layout_review_only")
