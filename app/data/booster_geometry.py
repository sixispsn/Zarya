"""Published connections, not a hydraulic design of external PBS pipework.

User's PBS catalogue, printed p.47 (PDF pp.46-47), SHA-256
9ef65b190b2bf3b824f70fd0998763e3552e59b3b6d356be17639df645911c50.
Bare CDM15 pump ports: CDM/CDMF catalogue p.60, SHA-256
abc39dac7beba67fe392c27a427f3f52c629474244901d8cc20deb7b6fccfac0.
Do not infer P1 from P2, nominal current, or the IE3 label.
"""
from app.data.booster_controls import booster_control


_CDM15 = {2: (2.2, 829), 3: (3., 934), 5: (4., 1035),
          7: (5.5, 1212), 9: (7.5, 1304), 11: (11., 1453)}


def booster_geometry(pump, counts):
    """Exact confirmed selection only; no match by model-name substring."""
    if not booster_control(pump) or counts is None or sum(counts) not in (2, 3):
        return None
    for stage, (p2, height) in _CDM15.items():
        if pump.model == f'CNP / Aikon PBS CDM15-{stage}':
            return dict(model=pump.model, installed_units=sum(counts),
                connection_dn=80, bare_pump_nozzle_dn=50,
                p2_motor_kw=p2, p1_input_kw=None, height_mm=height,
                source='CNP/Aikon, каталог PBS, с. 47; CDM/CDMF, с. 60',
                note='DN80 - присоединение установки; DN50 - патрубки насоса. '
                     'Диаметры внешних подводок и внутренней обвязки этим не назначены.')
    return None
