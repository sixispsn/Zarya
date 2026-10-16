"""Reproduce sampled Q-H values from the exact manufacturer vector PDF.

Development tool: python -m scripts.verify_rainwater_pump_catalog path/to/manual.pdf
Requires PyMuPDF, not a production dependency. A changed source requires review.
"""
import hashlib
from pathlib import Path
import sys

import pymupdf

from app.data.rainwater_pumps import CATALOG, Q_LPM, SOURCE_SHA256


def main(path):
    raw = Path(path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, "Manufacturer PDF changed"
    doc = pymupdf.open(stream=raw, filetype="pdf")
    drawings = doc[7].get_drawings()
    for pump, index in zip(CATALOG, (193, 196)):
        points = []
        for kind, a, b, c, d in drawings[index]['items']:
            assert kind == 'c'
            for i in range(101):
                t = i / 100
                p = a*((1-t)**3) + b*(3*(1-t)**2*t) + c*(3*(1-t)*t*t) + d*(t**3)
                points.append((p.x, p.y))
        points.sort()
        for lpm, (q, h) in zip(Q_LPM, pump['curve']):
            x = 66.058 + lpm * (393.23 - 66.058) / 120
            a, b = next((a, b) for a, b in zip(points, points[1:]) if a[0] <= x < b[0])
            y = a[1] + (b[1]-a[1])*(x-a[0])/(b[0]-a[0])
            actual = round((475.34-y)*160/(475.34-129.47), 1)
            assert abs(q-lpm*.06) < 1e-10 and h == actual, (pump['id'], lpm, h, actual)
    print('24 catalog samples verified against SHA-pinned manufacturer PDF')


if __name__ == '__main__':
    main(sys.argv[1])
