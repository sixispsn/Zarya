"""Place existing three-line A1 basement callouts without changing their content.

Only the ordinary, unscaled basement renderer is supported. Pipe centre-lines,
architectural edges and existing annotations are obstacles, never moved.
"""
from copy import deepcopy
from math import hypot
import re
from xml.etree import ElementTree as ET

from app.pz.leader_layout import _boxes_overlap, _segments_cross, _text_width


def hits_box(a, b, box):
    lo, hi = 0., 1.
    for origin, delta, minimum, maximum in (
        (a[0], b[0] - a[0], box[0], box[2]),
        (a[1], b[1] - a[1], box[1], box[3]),
    ):
        if abs(delta) < 1e-9:
            if not minimum <= origin <= maximum:
                return False
        else:
            first, last = sorted(((minimum - origin) / delta, (maximum - origin) / delta))
            lo, hi = max(lo, first), min(hi, last)
            if hi < lo:
                return False
    return True


def text_box(node):
    x, y, size = (float(node.get(k, "0")) for k in ("x", "y", "font-size"))
    width = _text_width("".join(node.itertext()), size)
    anchor = node.get("text-anchor", "start")
    left = x - (width if anchor == "end" else width / 2 if anchor == "middle" else 0)
    return left - 4, y - size - 4, left + width + 4, y + size * .25 + 4


def obstacles(root):
    lines, boxes = [], []

    def walk(node):
        if node.get("data-lower-node-callout") or node.get("data-title-block"):
            return
        # Inline pipe labels sit on separately retained continuous centre-lines.
        if node.get("transform") or node.tag.rsplit("}", 1)[-1] == "defs":
            return
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "line":
            lines.append(((float(node.get("x1")), float(node.get("y1"))),
                          (float(node.get("x2")), float(node.get("y2")))))
        elif tag == "text":
            boxes.append(text_box(node))
        elif tag == "rect" and node.get("stroke"):
            x, y, w, h = (float(node.get(k, "0")) for k in ("x", "y", "width", "height"))
            corners = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
            lines.extend(zip(corners, corners[1:] + corners[:1]))
        for child in node:
            walk(child)

    walk(root)
    return lines, boxes


def callout_geometry(group):
    path = next(n for n in group if n.tag.rsplit("}", 1)[-1] == "path")
    coords = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", path.get("d"))]
    assert len(coords) == 5  # Mx,y Lx,y Hx
    a, b, c = tuple(coords[:2]), tuple(coords[2:4]), (coords[4], coords[3])
    return ((a, b), (b, c)), [text_box(n) for n in group if n.tag.rsplit("}", 1)[-1] == "text"]


def clear(segments, boxes, other_lines, other_boxes):
    if any(_boxes_overlap(a, b, 4) for a in boxes for b in other_boxes):
        return False
    if any(hits_box(*line, box) for line in other_lines for box in boxes):
        return False
    if any(hits_box(*line, box) for line in segments for box in other_boxes):
        return False
    return not any(_segments_cross(a, b) for a in segments for b in other_lines)


def distinct_departure(segment, lines):
    """Keep a visible 15-degree separation from a pipe leaving the same target.

    This is a layout clearance, not a normative pipe-angle requirement.
    Oppositely directed rays are already distinct.
    """
    target, knee = segment
    dx, dy = knee[0] - target[0], knee[1] - target[1]
    for a, b in lines:
        if hypot(a[0] - target[0], a[1] - target[1]) < .1:
            other = b
        elif hypot(b[0] - target[0], b[1] - target[1]) < .1:
            other = a
        else:
            continue
        px, py = other[0] - target[0], other[1] - target[1]
        if dx * px + dy * py > 0 and abs(dx * py - dy * px) < .258819 * hypot(dx, dy) * hypot(px, py):
            return False
    return True


def layout_basement_callouts(svg):
    root = ET.fromstring(svg)
    if root.get("data-sheet-role") != "basement":
        raise ValueError("callout layout requires ordinary basement SVG")
    lines, boxes = obstacles(root)
    replacements = {}
    for original in (n for n in root.iter() if n.get("data-lower-node-callout")):
        group = deepcopy(original)
        target = tuple(float(group.get(f"data-callout-target-{a}")) for a in ("x", "y"))
        texts = [n for n in group if n.tag.rsplit("}", 1)[-1] == "text"]
        if len(texts) != 3:
            raise ValueError("basement callout requires all three original lines")
        width = max(_text_width(n.text or "", float(n.get("font-size"))) for n in texts) + 16
        path = next(n for n in group if n.tag.rsplit("}", 1)[-1] == "path")
        placed = False
        # Prefer free strips below the main; above is allowed only after the
        # same checks against risers, diagonals and existing annotations.
        for dy in (100, 135, 170, 205, -100, -135, -170, -205):
            shelf_y = target[1] + dy
            sides = (-1, 1) if target[0] > 1000 else (1, -1)
            for side in sides:
                starts = sorted(range(250, int(2420 - width), 25),
                                key=lambda x: abs(x + (width if side < 0 else 0) - target[0]))
                for left in starts:
                    knee_x, outer_x = (left, left + width) if side > 0 else (left + width, left)
                    if abs(knee_x - target[0]) < 20:
                        continue
                    path.set("d", f"M{target[0]:.1f},{target[1]:.1f} L{knee_x:.1f},{shelf_y:.1f} H{outer_x:.1f}")
                    for node, offset in zip(texts, (-9, 24, 47), strict=True):
                        node.set("x", f"{left + width - 8:.1f}")
                        node.set("y", f"{shelf_y + offset:.1f}")
                    segments, candidates = callout_geometry(group)
                    if max(b[3] for b in candidates) >= 1520 or min(b[1] for b in candidates) <= 250:
                        continue
                    if any(hits_box(*segments[0], box) for box in candidates):
                        continue
                    if not distinct_departure(segments[0], lines):
                        continue
                    if clear(segments, candidates, lines, boxes):
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
        if not placed:
            raise ValueError(f"cannot place complete basement callout: {group.get('data-lower-node-callout')}")
        lines.extend(segments)
        boxes.extend(candidates)
        for node in group.iter():
            node.tag = node.tag.rsplit("}", 1)[-1]
        replacements[group.get("data-lower-node-callout")] = ET.tostring(group, encoding="unicode")

    # Keep all non-callout SVG bytes untouched, including preview source geometry.
    def replace(match):
        key = ET.fromstring(match.group()).get("data-lower-node-callout")
        return replacements[key]

    return re.sub(r'<g data-lower-node-callout="[^>]+>.*?</g>', replace, svg, flags=re.S)
