"""Deterministic leader-line layout in final drawing coordinates.

The engine owns the graphical contract of a callout: a filled arrow at the
referenced element, one oblique leader segment, a horizontal shelf, the first
line above the shelf and the second line below it.  Text height is specified
in physical millimetres of the finished sheet rather than in incidental SVG
pixels, so embedding an engineering fragment cannot silently shrink labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from html import escape
from math import hypot

from fontTools.ttLib import TTFont

from app.pz.drafting_font import DRAFTING_FONT_FAMILY, DRAFTING_FONT_PATH


_OPENGOST_CAP_HEIGHT_RATIO = 0.823


@dataclass(frozen=True)
class LeaderBounds:
    left: float
    top: float
    right: float
    bottom: float

    def contains(self, box: tuple[float, float, float, float]) -> bool:
        x1, y1, x2, y2 = box
        return (
            self.left <= x1 <= x2 <= self.right
            and self.top <= y1 <= y2 <= self.bottom
        )


@dataclass(frozen=True)
class LeaderRequest:
    leader_id: str
    target_id: str
    target: tuple[float, float]
    title: str
    detail: str
    preferred_side: int = 1
    preferred_vertical: int = -1
    text_height_mm: float = 3.5
    arrow_kind: str = "closed-filled"


@dataclass(frozen=True)
class LeaderPlacement:
    knee: tuple[float, float]
    shelf_outer: tuple[float, float]
    text_box: tuple[float, float, float, float]
    title_xy: tuple[float, float]
    detail_xy: tuple[float, float]
    font_size: float


@lru_cache(maxsize=1)
def _font_metrics() -> tuple[int, dict[int, str], object]:
    font = TTFont(DRAFTING_FONT_PATH)
    return font["head"].unitsPerEm, font.getBestCmap(), font["hmtx"]


def _text_width(value: str, font_size: float) -> float:
    units_per_em, cmap, hmtx = _font_metrics()
    total = 0.0
    for character in value:
        glyph = cmap.get(ord(character)) or cmap.get(ord("?"))
        advance = hmtx[glyph][0] if glyph in hmtx.metrics else units_per_em * 0.5
        total += advance / units_per_em * font_size
    return total


def _boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    clearance: float,
) -> bool:
    return not (
        first[2] + clearance <= second[0]
        or second[2] + clearance <= first[0]
        or first[3] + clearance <= second[1]
        or second[3] + clearance <= first[1]
    )


def _orientation(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _segments_cross(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    a, b = first
    c, d = second
    return (
        _orientation(a, b, c) * _orientation(a, b, d) < 0
        and _orientation(c, d, a) * _orientation(c, d, b) < 0
    )


class LeaderLayoutEngine:
    """Place non-overlapping leaders within a bounded annotation zone."""

    def __init__(
        self,
        *,
        bounds: LeaderBounds,
        units_per_mm: float,
        clearance_mm: float = 2.0,
    ) -> None:
        if units_per_mm <= 0:
            raise ValueError("leader units_per_mm must be positive")
        self.bounds = bounds
        self.units_per_mm = units_per_mm
        self.clearance = clearance_mm * units_per_mm
        self._text_boxes: list[tuple[float, float, float, float]] = []
        self._segments: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def _candidate(
        self,
        request: LeaderRequest,
        *,
        side: int,
        vertical: int,
        horizontal_mm: float,
        vertical_mm: float,
    ) -> LeaderPlacement:
        font_size = (
            request.text_height_mm
            * self.units_per_mm
            / _OPENGOST_CAP_HEIGHT_RATIO
        )
        padding = 2.0 * self.units_per_mm
        gap = 0.8 * self.units_per_mm
        title_width = _text_width(request.title, font_size)
        detail_width = _text_width(request.detail, font_size)
        shelf_width = max(title_width, detail_width) + 2 * padding
        target_x, target_y = request.target
        shelf_y = target_y + vertical * vertical_mm * self.units_per_mm
        knee_x = target_x + side * horizontal_mm * self.units_per_mm
        outer_x = knee_x + side * shelf_width
        shelf_left, shelf_right = sorted((knee_x, outer_x))
        text_x = shelf_left + padding
        title_y = shelf_y - gap
        detail_y = shelf_y + font_size + gap
        text_box = (
            shelf_left,
            title_y - font_size,
            shelf_right,
            detail_y + font_size * 0.22,
        )
        return LeaderPlacement(
            knee=(knee_x, shelf_y),
            shelf_outer=(outer_x, shelf_y),
            text_box=text_box,
            title_xy=(text_x, title_y),
            detail_xy=(text_x, detail_y),
            font_size=font_size,
        )

    def place(self, request: LeaderRequest) -> LeaderPlacement:
        if not request.title.strip() or not request.detail.strip():
            raise ValueError("leader requires non-empty title and detail")
        if request.text_height_mm not in {3.5, 5.0}:
            raise ValueError("leader text height must be 3.5 or 5 mm")
        sides = (1 if request.preferred_side >= 0 else -1,)
        sides += (-sides[0],)
        verticals = (1 if request.preferred_vertical >= 0 else -1,)
        verticals += (-verticals[0],)
        for vertical in verticals:
            for side in sides:
                for vertical_mm in (18.0, 24.0, 30.0, 36.0):
                    for horizontal_mm in (18.0, 24.0, 30.0, 36.0):
                        placement = self._candidate(
                            request,
                            side=side,
                            vertical=vertical,
                            horizontal_mm=horizontal_mm,
                            vertical_mm=vertical_mm,
                        )
                        if not self.bounds.contains(placement.text_box):
                            continue
                        candidate_segments = (
                            (request.target, placement.knee),
                            (placement.knee, placement.shelf_outer),
                        )
                        if any(
                            _boxes_overlap(placement.text_box, row, self.clearance)
                            for row in self._text_boxes
                        ):
                            continue
                        if any(
                            _segments_cross(candidate, existing)
                            for candidate in candidate_segments
                            for existing in self._segments
                        ):
                            continue
                        self._text_boxes.append(placement.text_box)
                        self._segments.extend(candidate_segments)
                        return placement
        raise ValueError(f"cannot place leader without collision: {request.leader_id}")

    def render(self, request: LeaderRequest, placement: LeaderPlacement) -> str:
        target_x, target_y = request.target
        knee_x, shelf_y = placement.knee
        outer_x, _ = placement.shelf_outer
        vector_x = knee_x - target_x
        vector_y = shelf_y - target_y
        length = max(hypot(vector_x, vector_y), 1e-9)
        unit_x, unit_y = vector_x / length, vector_y / length
        arrow_length = 2.8 * self.units_per_mm
        arrow_half_width = 1.0 * self.units_per_mm
        base_x = target_x + unit_x * arrow_length
        base_y = target_y + unit_y * arrow_length
        perp_x, perp_y = -unit_y, unit_x
        arrow_path = (
            f"M{target_x:.3f},{target_y:.3f} "
            f"L{base_x+perp_x*arrow_half_width:.3f},"
            f"{base_y+perp_y*arrow_half_width:.3f} "
            f"L{base_x-perp_x*arrow_half_width:.3f},"
            f"{base_y-perp_y*arrow_half_width:.3f} Z"
        )
        stroke_width = 0.35 * self.units_per_mm
        title_x, title_y = placement.title_xy
        detail_x, detail_y = placement.detail_xy
        box_x1, box_y1, box_x2, box_y2 = placement.text_box
        return "".join((
            f'<g data-leader-id="{escape(request.leader_id)}" '
            f'data-leader-target="{escape(request.target_id)}" '
            f'data-target-x="{target_x:.3f}" data-target-y="{target_y:.3f}" '
            f'data-knee-x="{knee_x:.3f}" data-knee-y="{shelf_y:.3f}" '
            f'data-shelf-outer-x="{outer_x:.3f}" '
            f'data-shelf-outer-y="{shelf_y:.3f}" '
            f'data-text-box-x1="{box_x1:.3f}" data-text-box-y1="{box_y1:.3f}" '
            f'data-text-box-x2="{box_x2:.3f}" data-text-box-y2="{box_y2:.3f}" '
            f'data-arrow-kind="{escape(request.arrow_kind)}" '
            f'data-text-height-mm="{request.text_height_mm:g}" '
            'data-shelf-horizontal="true" data-title-above-shelf="true" '
            'data-detail-below-shelf="true">',
            f'<path data-leader-line="true" d="M{target_x:.3f},{target_y:.3f} '
            f'L{knee_x:.3f},{shelf_y:.3f} L{outer_x:.3f},{shelf_y:.3f}" '
            f'fill="none" stroke="#000" stroke-width="{stroke_width:.3f}"/>',
            f'<path data-leader-arrow="true" d="{arrow_path}" fill="#000"/>',
            f'<text data-leader-title="true" x="{title_x:.3f}" y="{title_y:.3f}" '
            f'font-family="{escape(DRAFTING_FONT_FAMILY)}" '
            f'font-size="{placement.font_size:.3f}">{escape(request.title)}</text>',
            f'<text data-leader-detail="true" x="{detail_x:.3f}" y="{detail_y:.3f}" '
            f'font-family="{escape(DRAFTING_FONT_FAMILY)}" '
            f'font-size="{placement.font_size:.3f}">{escape(request.detail)}</text>',
            '</g>',
        ))

    def place_and_render(self, request: LeaderRequest) -> str:
        placement = self.place(request)
        return self.render(request, placement)


__all__ = [
    "LeaderBounds",
    "LeaderLayoutEngine",
    "LeaderPlacement",
    "LeaderRequest",
]
