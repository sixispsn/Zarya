"""Безопасный первый проход по архитектурному PDF-плану.

Адаптер извлекает только наблюдаемые в PDF текстовые фрагменты и векторные
отрезки. Он не объявляет замкнутый контур помещением, не назначает этаж и не
угадывает масштаб. Все такие действия выполняются отдельным подтверждением
проектировщика перед созданием ``ArchitecturePlanRegistry``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Sequence

from pypdf import PdfReader


MAX_ARCHITECTURE_PDF_BYTES = 40 * 1024 * 1024
MAX_ARCHITECTURE_PAGES = 300
MAX_VECTOR_SEGMENTS_PER_PAGE = 150_000
MIN_VECTOR_SEGMENTS = 8


class ArchitecturePdfError(ValueError):
    """PDF нельзя безопасно передать на подтверждение архитектуры."""


@dataclass(frozen=True)
class PdfPlanPoint:
    x_pt: float
    y_pt: float


@dataclass(frozen=True)
class PdfPlanLineCandidate:
    start: PdfPlanPoint
    end: PdfPlanPoint
    line_width_pt: float
    paint_operator: str

    @property
    def length_pt(self) -> float:
        dx = self.end.x_pt - self.start.x_pt
        dy = self.end.y_pt - self.start.y_pt
        return (dx * dx + dy * dy) ** 0.5


@dataclass(frozen=True)
class PdfPlanTextCandidate:
    text: str
    anchor: PdfPlanPoint
    font_size_pt: float
    font_name: str


@dataclass(frozen=True)
class ArchitecturePdfIssue:
    code: str
    message: str
    severity: str
    page_number: int | None = None


@dataclass(frozen=True)
class ArchitecturePdfPageSurvey:
    page_number: int
    width_pt: float
    height_pt: float
    rotation_deg: int
    vector_lines: tuple[PdfPlanLineCandidate, ...]
    texts: tuple[PdfPlanTextCandidate, ...]
    image_count: int
    kind: str
    selectable_for_vector_confirmation: bool


@dataclass(frozen=True)
class ArchitecturePdfSurvey:
    original_name: str
    sha256: str
    pages: tuple[ArchitecturePdfPageSurvey, ...]
    issues: tuple[ArchitecturePdfIssue, ...]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def vector_page_count(self) -> int:
        return sum(row.selectable_for_vector_confirmation for row in self.pages)

    @property
    def requires_confirmation(self) -> bool:
        return True

    def to_mapping(self, *, include_candidates: bool = False) -> dict[str, Any]:
        pages = []
        for page in self.pages:
            row: dict[str, Any] = {
                "page_number": page.page_number,
                "width_pt": page.width_pt,
                "height_pt": page.height_pt,
                "rotation_deg": page.rotation_deg,
                "vector_line_count": len(page.vector_lines),
                "text_count": len(page.texts),
                "image_count": page.image_count,
                "kind": page.kind,
                "selectable_for_vector_confirmation": (
                    page.selectable_for_vector_confirmation
                ),
                "text_preview": [item.text for item in page.texts[:8]],
            }
            if include_candidates:
                row["vector_lines"] = [asdict(item) for item in page.vector_lines]
                row["texts"] = [asdict(item) for item in page.texts]
            pages.append(row)
        return {
            "original_name": self.original_name,
            "sha256": self.sha256,
            "page_count": self.page_count,
            "vector_page_count": self.vector_page_count,
            "requires_confirmation": self.requires_confirmation,
            "pages": pages,
            "issues": [asdict(item) for item in self.issues],
        }


def _number(value: Any) -> float:
    return float(value)


def _transform_point(matrix: Sequence[Any], x: float, y: float) -> PdfPlanPoint:
    a, b, c, d, e, f = (_number(value) for value in matrix[:6])
    return PdfPlanPoint(
        round(a * x + c * y + e, 4),
        round(b * x + d * y + f, 4),
    )


def _line_key(line: PdfPlanLineCandidate) -> tuple[object, ...]:
    start = (round(line.start.x_pt, 3), round(line.start.y_pt, 3))
    end = (round(line.end.x_pt, 3), round(line.end.y_pt, 3))
    first, second = sorted((start, end))
    return first + second + (round(line.line_width_pt, 3),)


def _deduplicate_lines(
    lines: Iterable[PdfPlanLineCandidate],
) -> tuple[PdfPlanLineCandidate, ...]:
    unique: dict[tuple[object, ...], PdfPlanLineCandidate] = {}
    for line in lines:
        if line.length_pt <= 0.05:
            continue
        unique.setdefault(_line_key(line), line)
    return tuple(unique.values())


def _deduplicate_texts(
    texts: Iterable[PdfPlanTextCandidate],
) -> tuple[PdfPlanTextCandidate, ...]:
    unique: dict[tuple[object, ...], PdfPlanTextCandidate] = {}
    for item in texts:
        key = (
            item.text,
            round(item.anchor.x_pt, 2),
            round(item.anchor.y_pt, 2),
            round(item.font_size_pt, 2),
        )
        unique.setdefault(key, item)
    return tuple(unique.values())


def _extract_page_candidates(page) -> tuple[
    tuple[PdfPlanLineCandidate, ...],
    tuple[PdfPlanTextCandidate, ...],
]:
    committed: list[PdfPlanLineCandidate] = []
    pending: list[tuple[PdfPlanPoint, PdfPlanPoint]] = []
    current: PdfPlanPoint | None = None
    subpath_start: PdfPlanPoint | None = None
    line_width = 1.0
    width_stack: list[float] = []
    texts: list[PdfPlanTextCandidate] = []

    def operand_before(operator, operands, ctm, _tm) -> None:
        nonlocal current, subpath_start, line_width, pending
        op = bytes(operator)
        if op == b"q":
            width_stack.append(line_width)
            return
        if op == b"Q":
            if width_stack:
                line_width = width_stack.pop()
            return
        if op == b"w" and operands:
            line_width = max(0.0, _number(operands[0]))
            return
        if op == b"m" and len(operands) >= 2:
            current = _transform_point(
                ctm, _number(operands[0]), _number(operands[1])
            )
            subpath_start = current
            return
        if op == b"l" and len(operands) >= 2:
            target = _transform_point(
                ctm, _number(operands[0]), _number(operands[1])
            )
            if current is not None:
                pending.append((current, target))
            current = target
            return
        if op == b"re" and len(operands) >= 4:
            x, y, width, height = (_number(row) for row in operands[:4])
            corners = (
                _transform_point(ctm, x, y),
                _transform_point(ctm, x + width, y),
                _transform_point(ctm, x + width, y + height),
                _transform_point(ctm, x, y + height),
            )
            pending.extend(
                (corners[index], corners[(index + 1) % 4])
                for index in range(4)
            )
            current = corners[0]
            subpath_start = current
            return
        if op == b"h":
            if current is not None and subpath_start is not None:
                pending.append((current, subpath_start))
                current = subpath_start
            return
        paint_operators = {
            b"S", b"s", b"B", b"B*", b"b", b"b*", b"f", b"F", b"f*",
        }
        discard_operators = {b"n"}
        if op in paint_operators:
            label = op.decode("ascii", errors="replace")
            for start, end in pending:
                if len(committed) >= MAX_VECTOR_SEGMENTS_PER_PAGE:
                    raise ArchitecturePdfError(
                        "На странице слишком много векторных сегментов. "
                        "Экспортируйте план отдельным листом без лишних слоёв."
                    )
                committed.append(
                    PdfPlanLineCandidate(start, end, line_width, label)
                )
            pending = []
            current = None
            subpath_start = None
        elif op in discard_operators:
            pending = []
            current = None
            subpath_start = None

    def visitor_text(text, ctm, text_matrix, font, font_size) -> None:
        cleaned = " ".join(str(text).replace("\x00", "").split())
        if not cleaned:
            return
        anchor_in_text = (
            _number(text_matrix[4]),
            _number(text_matrix[5]),
        )
        anchor = _transform_point(ctm, *anchor_in_text)
        font_name = ""
        if font is not None:
            font_name = str(font.get("/BaseFont", "")).lstrip("/")
        texts.append(
            PdfPlanTextCandidate(
                text=cleaned[:500],
                anchor=anchor,
                font_size_pt=round(abs(_number(font_size)), 3),
                font_name=font_name[:120],
            )
        )

    page.extract_text(
        visitor_operand_before=operand_before,
        visitor_text=visitor_text,
    )
    return _deduplicate_lines(committed), _deduplicate_texts(texts)


def _page_kind(line_count: int, text_count: int, image_count: int) -> str:
    if line_count >= MIN_VECTOR_SEGMENTS:
        return "vector"
    if line_count:
        return "vector_sparse"
    if image_count:
        return "raster"
    if text_count:
        return "text_only"
    return "empty"


def survey_architecture_pdf(
    source: str | Path | bytes,
    *,
    original_name: str | None = None,
) -> ArchitecturePdfSurvey:
    """Извлечь наблюдаемые кандидаты, не создавая проектных решений."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        content = path.read_bytes()
        name = original_name or path.name
    else:
        content = bytes(source)
        name = original_name or "architecture.pdf"
    if len(content) > MAX_ARCHITECTURE_PDF_BYTES:
        raise ArchitecturePdfError("Архитектурный PDF превышает лимит 40 МБ.")
    if not content.startswith(b"%PDF"):
        raise ArchitecturePdfError("Файл не является PDF.")
    try:
        reader = PdfReader(BytesIO(content), strict=False)
    except Exception as exc:
        raise ArchitecturePdfError("PDF повреждён или имеет неверную структуру.") from exc
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:
            raise ArchitecturePdfError("PDF защищён паролем.") from exc
        if not unlocked:
            raise ArchitecturePdfError("PDF защищён паролем.")
    if len(reader.pages) > MAX_ARCHITECTURE_PAGES:
        raise ArchitecturePdfError(
            f"В PDF больше {MAX_ARCHITECTURE_PAGES} страниц. "
            "Загрузите только листы планов."
        )

    pages: list[ArchitecturePdfPageSurvey] = []
    issues: list[ArchitecturePdfIssue] = []
    for page_number, page in enumerate(reader.pages, 1):
        try:
            lines, texts = _extract_page_candidates(page)
        except ArchitecturePdfError:
            raise
        except Exception as exc:
            raise ArchitecturePdfError(
                f"Не удалось разобрать векторный слой страницы {page_number}."
            ) from exc
        try:
            image_count = len(page.images)
        except Exception:
            image_count = 0
        width = abs(float(page.mediabox.width))
        height = abs(float(page.mediabox.height))
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        kind = _page_kind(len(lines), len(texts), image_count)
        selectable = kind == "vector"
        pages.append(
            ArchitecturePdfPageSurvey(
                page_number=page_number,
                width_pt=round(width, 3),
                height_pt=round(height, 3),
                rotation_deg=rotation,
                vector_lines=lines,
                texts=texts,
                image_count=image_count,
                kind=kind,
                selectable_for_vector_confirmation=selectable,
            )
        )
        if kind == "vector":
            issues.append(ArchitecturePdfIssue(
                "confirmation.required",
                "Нужно подтвердить масштаб, этаж, линию разреза, контуры и "
                "экспликацию помещений.",
                "required",
                page_number,
            ))
        elif kind == "vector_sparse":
            issues.append(ArchitecturePdfIssue(
                "vector.sparse",
                "Векторных линий недостаточно для выделения плана; проверьте "
                "экспорт и состав слоёв.",
                "warning",
                page_number,
            ))
        elif kind == "raster":
            issues.append(ArchitecturePdfIssue(
                "raster.ocr_required",
                "Страница выглядит растровой: требуется калибровка по размеру "
                "и ручное подтверждение контуров после OCR/векторизации.",
                "warning",
                page_number,
            ))
        else:
            issues.append(ArchitecturePdfIssue(
                "geometry.missing",
                "На странице не найден пригодный векторный план.",
                "warning",
                page_number,
            ))
    return ArchitecturePdfSurvey(
        original_name=Path(name).name,
        sha256=sha256(content).hexdigest(),
        pages=tuple(pages),
        issues=tuple(issues),
    )
