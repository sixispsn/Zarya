"""Compatibility entry points for IOS2 SVG previews."""


def build_metering_scheme_svg(project):
    """First sheet for SVG preview; PDF exports every inlet detail sheet."""
    from app.pz.metering_detail import build_metering_detail_pages
    return build_metering_detail_pages(project)[0]


def build_pump_zone_scheme_svg(project):
    """First sheet for SVG preview; PDF includes the separate HWS sheet."""
    from app.pz.water_station_drafting import build_pump_zone_scheme_pages
    return build_pump_zone_scheme_pages(project)[0]
