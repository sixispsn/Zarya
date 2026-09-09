"""Zarya application package initialization."""

# Cairo/Pango caches its font map on first use.  The application also reads
# architectural PDFs before it may generate an SPDS sheet, so the bundled
# drafting face must be registered before *any* CairoSVG render in the worker.
# Process-local registration does not install or modify a user/system font.
from app.pz.drafting_font import ensure_drafting_font_registered


ensure_drafting_font_registered()
