"""Graphical readings of SP10 Appendix B, supplied PDF p.35, image xref131.

Native raster 422x524 px. Values are graph tick locations, not measured product
curves. Only the DN50 aperture range 12..25 mm has been transcribed/checked.
Keep the source image/overlay audit: automatic output is study-only.
"""
SOURCE_SHA256 = '58126f661c57fe2e53d86c0bc0e202bfba395e8563eaf5c5875db437185ad86a'
IMAGE_XREF = 131
IMAGE_SIZE = (422, 524)

# (axis value, x, y) in native raster pixels. P is 100*delta_p(MPa), per amendment 1.
PRESSURE_TICKS = (
    (70,16,26),(60,16,47),(50,16,73),(40,16.5,103),(30,17,143),
    (20,17.5,198),(10,18.5,295),(9,18.5,309),(8,18.5,325),
    (7,18.5,344),(6,19,366),(5,19,391),(4,19.5,422),(3,20,461),(2,21.5,518))
FLOW_TICKS = ((2.5,408.5,23),(3,409.5,88),(4,410.5,189),(5,411.5,268),
              (6,412,333),(7,412.5,387),(8,413,435),(9,413,477),(10,413.5,514))
DN50_TICKS = tuple((d,x,y) for d,x,y in (
    (12,212,32),(12.5,212,49),(13,212,64),(13.5,212.5,79),
    (14,212.5,93),(14.5,213,107),(15,213,120),(15.5,213,133),
    (16,213.5,145),(16.5,213.5,157),(17,213.5,169),(17.5,213.5,180),
    (18,214,192),(18.5,214,202),(19,214,213),(19.5,214.5,223),
    (20,214.5,232),(20.5,214.5,242),(21,214.5,252),(21.5,215,261),
    (22,215,271),(22.5,215,279),(23,215,288),(23.5,215,297),
    (24,215,305),(24.5,215,313),(25,215,321)))

APOGEY_SOURCE = {
    'url': 'https://dn.ru/storage/certificates/apogej/diafragma/to_diafragma_apogej.pdf',
    'title': 'Техническое описание диафрагмы к пожарным кранам ООО «Апогей»',
    'pdf_page': 1,
    'sha256': '3bb759d3a50ae4ffbc0a8dad3ff4622cb006e1ba2c7132344aba9d4e6798a6cc',
    'apertures_mm': tuple(12+i*.5 for i in range(27)),
    'valve_dns': (50,65),
    'material': 'Латунь ЛС59-1',
    'evidence': 'manufacturer_document_on_distributor_host',
    'not_confirmed': ('aperture_tolerance','loss_curve','exact_valve_connection','maximum_pressure'),
    # Its 0.40 MPa/SNiP citation is obsolete, not used as a normative threshold.
    'obsolete_pressure_threshold_mpa_not_used': .40,
    'selection_confirmed': False,
}
