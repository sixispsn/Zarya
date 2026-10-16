"""Small, separate catalog for rainwater tanks. Never added to legacy PUMPS.

Q-H digitized from the manufacturer's vector PDF, page 8, paths 193/196.
Only 3..50 l/min is admitted: no extrapolation to the nameplate free discharge.
Graph values are approximate (0.1 m); acceptance includes the documented 15%
hydraulic tolerance and remains preliminary, not a supplier selection sheet.
"""
SOURCE = "https://jeelex.ru/upload/iblock/ce4/6x9ckloggyt7zba6xumh5inxjtsa2898/VODOMET-1.23_26.pdf"
SOURCE_SHA256 = "3f1d232b1c1160328641578a4735d8e9106e973bf37e947859ee1c9227906e3e"
Q_LPM = (3, 5, 10, 15, 20, 25, 30, 35, 40, 45, 48, 50)
CATALOG = (
    {"id": "vodomet-55-50-a", "model": "ДЖИЛЕКС ВОДОМЕТ 55/50 А", "article": "6550",
     "power_kw": 0.6, "shutoff_head_m": 50, "cable_m": 20,
     "curve": tuple(zip((q * 0.06 for q in Q_LPM), (49.2, 48.5, 46.5, 44.1, 41.1, 37.4, 32.9, 27.6, 21.6, 14.4, 9.5, 6.5)))},
    {"id": "vodomet-55-75-a", "model": "ДЖИЛЕКС ВОДОМЕТ 55/75 А", "article": "6575",
     "power_kw": 0.9, "shutoff_head_m": 75, "cable_m": 30,
     "curve": tuple(zip((q * 0.06 for q in Q_LPM), (73.8, 73.0, 70.4, 67.0, 62.9, 58.0, 52.3, 45.0, 36.0, 25.4, 18.4, 13.5)))},
)
