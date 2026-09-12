"""Paper-space lettering and line weights for assembled residential sheets.

Fragment coordinates are not paper millimetres. Apply this profile before
embedding so a 1/2 fragment does not halve the lettering or thin line weight.
It changes presentation only; hydraulic ports, values and topology stay owned
by their existing builders.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, sqrt
import re
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class DrawingSheetStyle:
    units_per_mm: float = 10 / 3
    annotation_height_mm: float = 2.5
    dimension_height_mm: float = 3.5
    thin_line_mm: float = 0.25
    main_line_mm: float = 0.6
    cap_height_ratio: float = 0.823

    def font_size(self, height_mm: float, fragment_scale: float) -> float:
        return height_mm * self.units_per_mm / fragment_scale / self.cap_height_ratio


RESIDENTIAL_SHEET_STYLE = DrawingSheetStyle()


def apply_residential_paper_style(content: str, *, fragment_scale: float = 0.5) -> str:
    style = RESIDENTIAL_SHEET_STYLE
    root = ET.fromstring(f'<g xmlns="http://www.w3.org/2000/svg">{content}</g>')
    ns = "{http://www.w3.org/2000/svg}"
    font = style.font_size(style.annotation_height_mm, fragment_scale)
    dim_font = style.font_size(style.dimension_height_mm, fragment_scale)
    thin = style.thin_line_mm * style.units_per_mm / fragment_scale
    main = style.main_line_mm * style.units_per_mm / fragment_scale
    room_boundaries = sorted(
        {float(row.get("x")) for row in root.iter() if row.get("data-building-room")}
    )

    # Short DN100 runs next to a WC cannot hold a full-size inline caption.
    # Place diameter + slope on a shelf above the appliance, with the leader
    # staying on the riser side of the WC instead of crossing its UGO.
    for floor in (x for x in root.iter() if x.get("data-floor-assembly")):
        segments = {
            x.get("data-floor-segment"): x for x in floor if x.get("data-floor-segment")
        }
        for slope in (r for r in floor if r.get("data-slope-marker")):
            first = segments.get(slope.get("data-first-segment"))
            if first is None or first.get("data-dn") != "50":
                continue
            direction = 1 if float(first.get("x2")) > float(first.get("x1")) else -1
            h = style.dimension_height_mm * style.units_per_mm / fragment_scale
            caption_width = 5 * dim_font * 0.56 + 1.5 * h + 6
            candidates = []
            for line in segments.values():
                if (
                    line.get("data-role") != "common_floor_branch"
                    or line.get("data-dn") != "50"
                ):
                    continue
                lo, hi = sorted((float(line.get("x1")), float(line.get("x2"))))
                centre = (lo + hi) / 2
                if hi - lo < caption_width + 20 or any(
                    centre - caption_width / 2 - 6 < x < centre + caption_width / 2 + 6
                    for x in room_boundaries
                ):
                    continue
                candidates.append(centre)
            if candidates:
                # Prefer the first readable run from the source appliances;
                # the downstream bay is already reserved for the WC callout.
                centre = candidates[0]
                slope.set(
                    "data-paper-slope-x", str(centre + direction * caption_width / 2)
                )
                cleanout_captions = [
                    r for r in floor if r.tag == ns + "text" and r.text == "Прочистка"
                ]
                if any(
                    centre + caption_width / 2 > float(r.get("x")) - 6
                    and centre - caption_width / 2 < float(r.get("x")) + font * 5
                    for r in cleanout_captions
                ):
                    slope.set(
                        "data-paper-slope-y",
                        str(min(float(first.get("y1")), float(first.get("y2"))) - 85),
                    )
        # Socket ends follow DN on the appliance branches as well. One shared
        # boundary identifies the direct elbow/wye joint on the short diagonal.
        for fitting in tuple(floor):
            fitting_id = fitting.get("data-floor-fitting", "")
            if (
                not fitting_id.endswith("_wye_45")
                or fitting_id == "riser_branch_wye_45"
            ):
                continue
            joint = next(
                (
                    r
                    for r in floor
                    if r.get("data-end-fitting") == fitting_id
                    and "elbow" in r.get("data-start-fitting", "")
                ),
                None,
            )
            if joint is None:
                continue
            elbow = (float(joint.get("x1")), float(joint.get("y1")))
            wye = (float(joint.get("x2")), float(joint.get("y2")))
            outgoing = next(
                (
                    r
                    for r in segments.values()
                    if r.get("data-role") == "common_floor_branch"
                    and abs(float(r.get("x1")) - wye[0]) < 0.2
                    and abs(float(r.get("y1")) - wye[1]) < 0.2
                ),
                None,
            )
            if outgoing is None:
                continue
            end = (float(outgoing.get("x2")), float(outgoing.get("y2")))
            sizes = FittingGraphicSize(
                int(joint.get("data-dn")),
                int(outgoing.get("data-dn")),
                style.units_per_mm / fragment_scale,
            )
            upstream = (2 * wye[0] - end[0], 2 * wye[1] - end[1])
            transition = next(
                (r for r in floor if r.get("data-adjacent-fitting") == fitting_id), None
            )
            for child in tuple(fitting):
                fitting.remove(child)
            for target, name in ((upstream, "inlet"), (end, "outlet")):
                fitting.append(
                    ET.fromstring(
                        sizes.boundary(
                            wye,
                            target,
                            offset=sizes.main_socket,
                            dn=sizes.main_dn,
                            marker=f"{fitting_id}-{name}",
                        )
                    )
                )
            if transition is not None:
                dx, dy = end[0] - wye[0], end[1] - wye[1]
                length = hypot(dx, dy)
                ux, uy = dx / length, dy / length
                bx, by = (
                    wye[0] - ux * sizes.main_socket,
                    wye[1] - uy * sizes.main_socket,
                )
                depth = 2.5 * style.units_per_mm / fragment_scale
                half = sizes.tick_half(sizes.main_dn)
                ax, ay = bx - ux * depth, by - uy * depth
                triangle = f"M{ax:.3f},{ay:.3f} L{bx - uy * half:.3f},{by + ux * half:.3f} L{bx + uy * half:.3f},{by - ux * half:.3f} Z"
                for path in transition:
                    path.set("d", triangle)
                transition.set("data-fitting-socket-offset", str(sizes.main_socket))
            elbow_group = next(
                (
                    r
                    for r in floor
                    if r.get("data-floor-fitting") == joint.get("data-start-fitting")
                ),
                None,
            )
            if elbow_group is not None:
                inlet = next(
                    (
                        r
                        for r in segments.values()
                        if abs(float(r.get("x2")) - elbow[0]) < 0.2
                        and abs(float(r.get("y2")) - elbow[1]) < 0.2
                    ),
                    None,
                )
                if inlet is not None:
                    for child in tuple(elbow_group):
                        elbow_group.remove(child)
                    start = (float(inlet.get("x1")), float(inlet.get("y1")))
                    elbow_group.append(
                        ET.fromstring(
                            sizes.boundary(
                                elbow,
                                start,
                                offset=min(
                                    sizes.branch_socket,
                                    hypot(start[0] - elbow[0], start[1] - elbow[1]) / 2,
                                ),
                                dn=sizes.branch_dn,
                                marker=f"{fitting_id}-elbow-inlet",
                            )
                        )
                    )
                    shared = ((elbow[0] + wye[0]) / 2, (elbow[1] + wye[1]) / 2)
                    elbow_group.append(
                        ET.fromstring(
                            sizes.boundary(
                                shared,
                                wye,
                                offset=0,
                                dn=sizes.branch_dn,
                                marker=f"{fitting_id}-direct-joint",
                            )
                        )
                    )
        short = segments.get("collector_to_riser")
        marker = next(
            (x for x in floor if x.get("data-pipe-line-id") == "floor-branch-2"), None
        )
        slope = next(
            (x for x in floor if x.get("data-first-segment") == "collector_to_riser"),
            None,
        )
        if short is None or marker is None or slope is None:
            continue
        sx, sy, ex, ey = (float(short.get(k)) for k in ("x1", "y1", "x2", "y2"))
        direction = 1 if ex > sx else -1
        target_x, target_y = (sx + ex) / 2, (sy + ey) / 2
        knee_x, shelf_y = target_x - direction * 10, target_y - 116
        outer_x = knee_x - direction * 155
        marker.set(
            "transform",
            f"translate({(knee_x + outer_x) / 2:.3f} {shelf_y - 20:.3f}) rotate(0)",
        )
        marker.set("data-caption-placement", "shelf-above-short-pipe")
        slope.set("data-paper-slope-x", str(knee_x - direction * 10))
        slope.set("data-paper-slope-y", str(shelf_y + 33))
        dx, dy = knee_x - target_x, shelf_y - target_y
        length = hypot(dx, dy)
        ux, uy = dx / length, dy / length
        arrow_length, half = (
            2.8 * style.units_per_mm / fragment_scale,
            0.8 * style.units_per_mm / fragment_scale,
        )
        bx, by = target_x + ux * arrow_length, target_y + uy * arrow_length
        group = ET.SubElement(
            floor,
            ns + "g",
            {"data-short-pipe-callout": short.get("data-floor-segment")},
        )
        ET.SubElement(
            group,
            ns + "path",
            {
                "d": f"M{target_x:.3f},{target_y:.3f} L{knee_x:.3f},{shelf_y:.3f} L{outer_x:.3f},{shelf_y:.3f}",
                "fill": "none",
                "stroke": "#000",
                "stroke-width": str(thin),
            },
        )
        ET.SubElement(
            group,
            ns + "path",
            {
                "d": f"M{target_x:.3f},{target_y:.3f} L{bx - uy * half:.3f},{by + ux * half:.3f} L{bx + uy * half:.3f},{by - ux * half:.3f} Z",
                "fill": "#000",
            },
        )
        wc = next((x for x in floor if x.get("data-kind") == "toilet"), None)
        quantity = next(
            (
                x
                for x in floor
                if wc is not None
                and x.get("data-floor-fixture-quantity") == wc.get("data-floor-fixture")
            ),
            None,
        )
        if quantity is not None:
            quantity.set("x", str(sx - direction * 48))
            quantity.set("y", str(sy - 48))
            quantity.set("text-anchor", "end" if direction > 0 else "start")
        for text in floor:
            if text.get("data-fitting-label"):
                text.set("x", str(ex + direction * 60))
                text.set("y", str(shelf_y - 20))
                text.set("text-anchor", "middle")
            if text.tag == ns + "text" and (text.text or "").startswith("К1 ⌀"):
                text.set("y", str(float(text.get("y")) + 18))

    # Vertical labels must clear slab outlines and the section cut. Otherwise
    # their white pipe gaps erase a slab or leave half a caption at the knife.
    barriers = []
    for row in root.iter():
        if row.get("data-building-slab") or row.get("data-building-roof-boundary"):
            y = float(row.get("y"))
            barriers.append((y - 6, y + float(row.get("height")) + 6))
        if row.get("data-section-break-line"):
            values = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", row.get("d"))]
            barriers.append((min(values[1::2]) - 6, max(values[1::2]) + 6))
    for parent in root.iter():
        for label in parent:
            if not label.get("data-inline-pipe-label"):
                continue
            transform = label.get("transform", "")
            match = re.match(
                r"translate\(([-\d.]+) ([-\d.]+)\) rotate\(([-\d.]+)\)", transform
            )
            if not match or abs(float(match[3])) != 90:
                continue
            x, y = float(match[1]), float(match[2])
            half = len(label.get("data-inline-pipe-label")) * font * 0.56 / 2 + 8
            line = next(
                (
                    r
                    for r in parent
                    if r.tag == ns + "line"
                    and abs(float(r.get("x1", "nan")) - x) < 0.5
                    and abs(float(r.get("x2", "nan")) - x) < 0.5
                ),
                None,
            )
            if line is None:
                continue
            lo, hi = sorted((float(line.get("y1")), float(line.get("y2"))))
            candidates = [y] + [
                lo + half + (hi - lo - 2 * half) * i / 20 for i in range(21)
            ]
            valid = [
                cy
                for cy in candidates
                if lo + half <= cy <= hi - half
                and all(cy + half < a or cy - half > b for a, b in barriers)
            ]
            if not valid:
                continuation = any(
                    r.tag == ns + "line"
                    and r is not line
                    and abs(float(r.get("x1", "nan")) - x) < 0.5
                    and abs(float(r.get("x2", "nan")) - x) < 0.5
                    and abs(float(r.get("y1", "nan")) - hi) < 0.5
                    for r in root.iter()
                )
                if continuation:
                    candidates = [
                        lo + half + (hi - lo - half) * i / 30 for i in range(31)
                    ]
                    valid = [
                        cy
                        for cy in candidates
                        if all(cy + half < a or cy - half > b for a, b in barriers)
                    ]
            if valid:
                y = min(valid, key=lambda cy: abs(cy - y))
                label.set("transform", f"translate({x:.3f} {y:.3f}) rotate({match[3]})")

    def visit(row: ET.Element, ancestors: tuple[ET.Element, ...] = ()) -> None:
        tag = row.tag.rsplit("}", 1)[-1]
        if row.get("data-inline-pipe-label"):
            text = next(child for child in row.iter() if child.tag == ns + "text")
            old_font = float(text.get("font-size"))
            factor = font / old_font
            wrapper = ET.Element(ns + "g", {"transform": f"scale({factor:.6f})"})
            for child in tuple(row):
                row.remove(child)
                wrapper.append(child)
            row.append(wrapper)
            row.set("data-paper-text-height-mm", "2.5")
            return

        if row.get("data-slope-marker"):
            text = next(child for child in row if child.tag == ns + "text")
            path = next(child for child in row if child.tag == ns + "path")
            coords = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", path.get("d"))]
            apex_x, old_y = coords[2:4]
            apex_x = float(row.get("data-paper-slope-x", str(apex_x)))
            direction = 1 if text.get("text-anchor") == "end" else -1
            # Both limbs use the dimension height; the lower limb is horizontal.
            h = style.dimension_height_mm * style.units_per_mm / fragment_scale
            arm_x = apex_x - direction * 1.5 * h
            y = float(row.get("data-paper-slope-y", str(old_y - 10)))
            path.set(
                "d",
                f"M{arm_x:.3f},{y - h:.3f} L{apex_x:.3f},{y:.3f} L{arm_x:.3f},{y:.3f}",
            )
            path.set("stroke-width", f"{thin:.3f}")
            text.set("x", f"{arm_x - direction * 6:.3f}")
            text.set("y", f"{y:.3f}")
            text.set("font-size", f"{dim_font:.3f}")
            text.set("data-paper-text-height-mm", "3.5")
            row.set("data-sign-shape", "acute-angle")
            row.set("data-lower-leg-horizontal", "true")
            row.set("data-paper-text-height-mm", "3.5")
            return

        if tag == "text":
            # Revision dimensions and level numbers use the same size as slopes.
            is_dimension = bool(re.fullmatch(r"\d{3,4}", row.text or "")) or (
                any(parent.get("data-building-level-mark") for parent in ancestors)
                and (row.text or "").startswith(("+", "-", "±"))
            )
            target = dim_font if is_dimension else font
            current = float(row.get("font-size", str(font)))
            # Room and fixture-count captions were already paper-compensated.
            row.set("font-size", f"{max(target, current):.3f}")
            row.set("data-paper-text-height-mm", "3.5" if is_dimension else "2.5")
            row.set("fill", "#000")
            if row.get("data-residential-room-label") and row.text == "Лифтовой холл":
                row.text = None
                x, y = row.get("x"), float(row.get("y"))
                for index, value in enumerate(("Лифтовой", "холл")):
                    ET.SubElement(
                        row, ns + "tspan", {"x": x, "y": str(y + 24 * index)}
                    ).text = value
            if row.get("data-funnel-caption"):
                row.set("x", str(float(row.get("x")) + 20))
            if row.get("data-funnel-caption") == "id":
                row.set("y", str(float(row.get("y")) - 44))
            if row.get("data-funnel-caption") == "description":
                value = row.text or ""
                row.text = None
                y = float(row.get("y")) - 35
                row.set("y", str(y))
                for index, value in enumerate(
                    (value.split("; с ")[0], "электрообогрев")
                ):
                    ET.SubElement(
                        row, ns + "tspan", {"x": row.get("x"), "y": str(y + index * 26)}
                    ).text = value
            if is_dimension and (row.text or "").isdigit():
                # Dimension numbers follow their vertical dimension line.
                x, y = float(row.get("x")), float(row.get("y"))
                row.set("text-anchor", "middle")
                row.set("transform", f"rotate(-90 {x:.3f} {y:.3f})")
            if (row.text or "").startswith("Выпуск "):
                value = row.text.replace(" за грань здания", "")
                row.text = None
                row.set("text-anchor", "end")
                row.set("x", "2650")
                y = float(row.get("y"))
                for index, value in enumerate((value, "за грань здания")):
                    ET.SubElement(
                        row, ns + "tspan", {"x": "2650", "y": str(y + 26 * index)}
                    ).text = value
            if row.text == "наружная грань здания":
                row.text = "грань здания"
                row.set("text-anchor", "end")
                row.set("x", "2660")
        elif row.get("stroke") not in (None, "none", "white", "#fff"):
            raw = float(row.get("stroke-width", "1"))
            pipe = any(
                parent.get("data-building-pipe-line")
                or parent.get("data-draft-segment")
                or parent.get("data-floor-segment")
                for parent in (*ancestors, row)
            )
            nested_scale = 1.0
            for parent in ancestors:
                match = re.search(r"scale\(([\d.]+)", parent.get("transform", ""))
                if match:
                    nested_scale *= float(match.group(1))
                matrix = re.search(r"matrix\(([^)]+)\)", parent.get("transform", ""))
                if matrix:
                    a, b, c, d, _, _ = map(
                        float, re.split(r"[ ,]+", matrix.group(1).strip())
                    )
                    nested_scale *= sqrt(abs(a * d - b * c))
            ugo = any(parent.get("data-ugo") for parent in ancestors)
            width = main if pipe or (raw >= 3 and not ugo) else thin
            row.set("stroke-width", f"{width / nested_scale:.3f}")
            row.set(
                "data-paper-line-width-mm",
                str(style.main_line_mm if width == main else style.thin_line_mm),
            )
        for child in tuple(row):
            visit(child, ancestors + (row,))

    visit(root)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    return "".join(ET.tostring(child, encoding="unicode") for child in root)


@dataclass(frozen=True)
class FittingGraphicSize:
    """Approximate DN-proportional symbol, not a manufacturer's dimension."""

    branch_dn: int
    main_dn: int
    units_per_paper_mm: float

    @property
    def main_socket(self) -> float:
        return 3.0 * self.main_dn / 100 * self.units_per_paper_mm

    @property
    def branch_socket(self) -> float:
        return 3.0 * self.branch_dn / 100 * self.units_per_paper_mm

    def tick_half(self, dn: int) -> float:
        return max(0.75, 0.9 * dn / 100) * self.units_per_paper_mm

    def boundary(
        self,
        point: tuple[float, float],
        toward: tuple[float, float],
        *,
        offset: float,
        dn: int,
        marker: str,
    ) -> str:
        dx, dy = toward[0] - point[0], toward[1] - point[1]
        length = hypot(dx, dy)
        ux, uy = dx / length, dy / length
        x, y = point[0] + ux * offset, point[1] + uy * offset
        half = self.tick_half(dn)
        return (
            f'<path data-fitting="{marker}" data-fitting-size-dn="{dn}" '
            'data-fitting-proportions="dn-multiple" '
            f'd="M{x - uy * half:.3f},{y + ux * half:.3f} L{x + uy * half:.3f},{y - ux * half:.3f}" '
            'fill="none" stroke="#000" '
            f'stroke-width="{0.25 * self.units_per_paper_mm:.3f}"/>'
        )
