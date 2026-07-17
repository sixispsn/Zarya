"""
Таблицы СП 10.13130.2020 для расчёта внутреннего противопожарного водопровода (ВПВ).

Таблица 7.3 — расход и давление диктующего пожарного крана (ПК)
              в зависимости от DN клапана, диаметра ствола, длины рукава, высоты струи.

Перенесено 1-в-1 из legacy/sp30_calculator.html (объект T73).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FireNozzleData:
    """Параметры диктующего ПК: расход и давление."""
    q: float   # расход, л/с
    p: float   # давление у клапана, МПа


# ============================================================
# ТАБЛИЦА 7.3 СП 10.13130.2020
# Ключ: (DN_клапана, диаметр_ствола_мм, длина_рукава_м, высота_струи_м)
# ============================================================

FIRE_NOZZLE_TABLE: dict[tuple[int, int, int, int], FireNozzleData] = {
    # DN50, ствол 13 мм
    (50, 13, 10, 12): FireNozzleData(2.6, 0.202), (50, 13, 15, 12): FireNozzleData(2.6, 0.206), (50, 13, 20, 12): FireNozzleData(2.6, 0.210),
    (50, 13, 10, 14): FireNozzleData(2.8, 0.236), (50, 13, 15, 14): FireNozzleData(2.8, 0.241), (50, 13, 20, 14): FireNozzleData(2.8, 0.245),
    (50, 13, 10, 16): FireNozzleData(3.2, 0.316), (50, 13, 15, 16): FireNozzleData(3.2, 0.322), (50, 13, 20, 16): FireNozzleData(3.2, 0.328),
    (50, 13, 10, 18): FireNozzleData(3.6, 0.390), (50, 13, 15, 18): FireNozzleData(3.6, 0.398), (50, 13, 20, 18): FireNozzleData(3.6, 0.406),
    # DN50, ствол 16 мм
    (50, 16, 10, 6): FireNozzleData(2.6, 0.092), (50, 16, 15, 6): FireNozzleData(2.6, 0.096), (50, 16, 20, 6): FireNozzleData(2.6, 0.100),
    (50, 16, 10, 8): FireNozzleData(2.9, 0.120), (50, 16, 15, 8): FireNozzleData(2.9, 0.125), (50, 16, 20, 8): FireNozzleData(2.9, 0.130),
    (50, 16, 10, 10): FireNozzleData(3.3, 0.151), (50, 16, 15, 10): FireNozzleData(3.3, 0.157), (50, 16, 20, 10): FireNozzleData(3.3, 0.164),
    (50, 16, 10, 12): FireNozzleData(3.7, 0.192), (50, 16, 15, 12): FireNozzleData(3.7, 0.196), (50, 16, 20, 12): FireNozzleData(3.7, 0.210),
    (50, 16, 10, 14): FireNozzleData(4.2, 0.248), (50, 16, 15, 14): FireNozzleData(4.2, 0.255), (50, 16, 20, 14): FireNozzleData(4.2, 0.263),
    (50, 16, 10, 16): FireNozzleData(4.6, 0.293), (50, 16, 15, 16): FireNozzleData(4.6, 0.300), (50, 16, 20, 16): FireNozzleData(4.6, 0.318),
    (50, 16, 10, 18): FireNozzleData(5.1, 0.360), (50, 16, 15, 18): FireNozzleData(5.1, 0.380), (50, 16, 20, 18): FireNozzleData(5.1, 0.400),
    # DN50, ствол 19 мм
    (50, 19, 10, 6): FireNozzleData(3.4, 0.088), (50, 19, 15, 6): FireNozzleData(3.4, 0.096), (50, 19, 20, 6): FireNozzleData(3.4, 0.104),
    (50, 19, 10, 8): FireNozzleData(4.1, 0.129), (50, 19, 15, 8): FireNozzleData(4.1, 0.138), (50, 19, 20, 8): FireNozzleData(4.1, 0.148),
    (50, 19, 10, 10): FireNozzleData(4.6, 0.160), (50, 19, 15, 10): FireNozzleData(4.6, 0.173), (50, 19, 20, 10): FireNozzleData(4.6, 0.185),
    (50, 19, 10, 12): FireNozzleData(5.2, 0.206), (50, 19, 15, 12): FireNozzleData(5.2, 0.223), (50, 19, 20, 12): FireNozzleData(5.2, 0.240),
    # DN65, ствол 13 мм
    (65, 13, 10, 12): FireNozzleData(2.6, 0.198), (65, 13, 15, 12): FireNozzleData(2.6, 0.199), (65, 13, 20, 12): FireNozzleData(2.6, 0.201),
    (65, 13, 10, 14): FireNozzleData(2.8, 0.230), (65, 13, 15, 14): FireNozzleData(2.8, 0.231), (65, 13, 20, 14): FireNozzleData(2.8, 0.233),
    (65, 13, 10, 16): FireNozzleData(3.2, 0.310), (65, 13, 15, 16): FireNozzleData(3.2, 0.313), (65, 13, 20, 16): FireNozzleData(3.2, 0.315),
    (65, 13, 10, 18): FireNozzleData(3.6, 0.380), (65, 13, 15, 18): FireNozzleData(3.6, 0.383), (65, 13, 20, 18): FireNozzleData(3.6, 0.385),
    (65, 13, 10, 20): FireNozzleData(4.0, 0.464), (65, 13, 15, 20): FireNozzleData(4.0, 0.467), (65, 13, 20, 20): FireNozzleData(4.0, 0.470),
    # DN65, ствол 16 мм
    (65, 16, 10, 6): FireNozzleData(2.6, 0.088), (65, 16, 15, 6): FireNozzleData(2.6, 0.089), (65, 16, 20, 6): FireNozzleData(2.6, 0.090),
    (65, 16, 10, 8): FireNozzleData(2.9, 0.110), (65, 16, 15, 8): FireNozzleData(2.9, 0.112), (65, 16, 20, 8): FireNozzleData(2.9, 0.114),
    (65, 16, 10, 10): FireNozzleData(3.3, 0.140), (65, 16, 15, 10): FireNozzleData(3.3, 0.143), (65, 16, 20, 10): FireNozzleData(3.3, 0.146),
    (65, 16, 10, 12): FireNozzleData(3.7, 0.180), (65, 16, 15, 12): FireNozzleData(3.7, 0.183), (65, 16, 20, 12): FireNozzleData(3.7, 0.186),
    (65, 16, 10, 14): FireNozzleData(4.2, 0.230), (65, 16, 15, 14): FireNozzleData(4.2, 0.233), (65, 16, 20, 14): FireNozzleData(4.2, 0.236),
    (65, 16, 10, 16): FireNozzleData(4.6, 0.276), (65, 16, 15, 16): FireNozzleData(4.6, 0.280), (65, 16, 20, 16): FireNozzleData(4.6, 0.284),
    (65, 16, 10, 18): FireNozzleData(5.1, 0.338), (65, 16, 15, 18): FireNozzleData(5.1, 0.342), (65, 16, 20, 18): FireNozzleData(5.1, 0.346),
    (65, 16, 10, 20): FireNozzleData(5.6, 0.412), (65, 16, 15, 20): FireNozzleData(5.6, 0.418), (65, 16, 20, 20): FireNozzleData(5.6, 0.424),
    # DN65, ствол 19 мм
    (65, 19, 10, 6): FireNozzleData(3.4, 0.078), (65, 19, 15, 6): FireNozzleData(3.4, 0.080), (65, 19, 20, 6): FireNozzleData(3.4, 0.083),
    (65, 19, 10, 8): FireNozzleData(4.1, 0.114), (65, 19, 15, 8): FireNozzleData(4.1, 0.117), (65, 19, 20, 8): FireNozzleData(4.1, 0.121),
    (65, 19, 10, 10): FireNozzleData(4.6, 0.143), (65, 19, 15, 10): FireNozzleData(4.6, 0.147), (65, 19, 20, 10): FireNozzleData(4.6, 0.151),
    (65, 19, 10, 12): FireNozzleData(5.2, 0.182), (65, 19, 15, 12): FireNozzleData(5.2, 0.190), (65, 19, 20, 12): FireNozzleData(5.2, 0.199),
    (65, 19, 10, 14): FireNozzleData(5.7, 0.218), (65, 19, 15, 14): FireNozzleData(5.7, 0.224), (65, 19, 20, 14): FireNozzleData(5.7, 0.230),
    (65, 19, 10, 16): FireNozzleData(6.3, 0.266), (65, 19, 15, 16): FireNozzleData(6.3, 0.273), (65, 19, 20, 16): FireNozzleData(6.3, 0.280),
    (65, 19, 10, 18): FireNozzleData(7.0, 0.329), (65, 19, 15, 18): FireNozzleData(7.0, 0.338), (65, 19, 20, 18): FireNozzleData(7.0, 0.348),
    (65, 19, 10, 20): FireNozzleData(7.5, 0.372), (65, 19, 15, 20): FireNozzleData(7.5, 0.385), (65, 19, 20, 20): FireNozzleData(7.5, 0.397),
}


def get_nozzle_data(dn: int, nozzle: int, hose: int, jet: int) -> FireNozzleData | None:
    """Получить расход и давление диктующего ПК из таблицы 7.3."""
    return FIRE_NOZZLE_TABLE.get((dn, nozzle, hose, jet))
