"""Tank pump duty check, an explicit extension, not a legacy V1 calculation.

Uses the shared approved catalog interpolation. Does NOT reconstruct a system
curve from one point, invent hose resistance, size tanks or alter V1/K2 flows.
Losses are supplied at Q_design with a calculation/passport reference.
"""
import math

from app.calc.pump_curve import interpolate_head
from app.data.rainwater_pumps import CATALOG, SOURCE

SETUPS = {"submersible_irrigation": "Погружной насос · полив из бака"}
HOSES = {"none": "Без шланга · стационарная сеть", "custom": "Поливочный шланг · по паспорту"}
NUMBERS = {
    "pump_flow_lps": (False, False), "pump_geometric_head_m": (True, True),
    "pump_terminal_head_m": (True, False), "pump_network_loss_m": (True, False),
    "pump_treatment_loss_m": (True, False), "pump_min_submergence_m": (False, False),
    "pump_max_submergence_m": (False, False), "pump_temperature_c": (False, False),
    "pump_pipe_inner_mm": (False, False), "pump_pipe_length_m": (False, False),
    "hose_length_m": (False, False), "hose_inner_mm": (False, False),
    "hose_pn_bar": (False, False), "hose_loss_m": (True, False),
    "hose_sets": (False, False), "outlets_count": (False, False),
}
TEXTS = ("pump_loss_source", "hose_model")


def validate(data):
    errors = []
    for key, (zero, signed) in NUMBERS.items():
        v = getattr(data, key)
        if v is None:
            continue
        if type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 or (not signed and (v < 0 or (v == 0 and not zero))):
            errors.append(f"Насос дождевой воды: некорректное {key}.")
        elif key in {"hose_sets", "outlets_count"} and (int(v) != v or v > 1000):
            errors.append(f"{key}: целое количество от 1 до 1000.")
    for key in TEXTS:
        if not isinstance(getattr(data, key), str) or len(getattr(data, key)) > 200:
            errors.append(f"{key}: текст до 200 символов.")
    for key, choices in (("pump_setup", SETUPS), ("hose_choice", HOSES), ("pump_clean_water", {"yes", "no"})):
        if not isinstance(getattr(data, key), str) or getattr(data, key) not in {"", *choices}:
            errors.append(f"Неизвестное значение {key}.")
    return errors


def assess_pump(d, *, building_kind=None, roof_kind=None):
    r = {"status": "not_configured", "missing": [], "errors": [], "candidates": [],
         "selected": None, "duty": None, "source": SOURCE,
         "method": "Проверка каталога при расчётных Q/H, не фактическое пересечение характеристик. Потери заданы при этом расходе; коэффициенты В1 сюда не добавляются.",
         "pending": [
             "Подтверждение изготовителем рабочей области, качества воды и компоновки в баке.",
             "Автоматика остановки при закрытых кранах, не более 20 пусков/ч; гидроаккумулятор и уставки по режиму.",
             "Защита от гидроудара, проверка давления всех деталей и отметок низших точек; питание 220 В, заземление и УЗО 30 мА по паспорту.",
             "Безопасный перелив, опорожнение бака, санитарная обработка, доступ и защита от замерзания.",
         ]}
    if not d.enabled or not d.pump_setup:
        return r
    from app.calc.rainwater_treatment import assess_treatment
    treatment = assess_treatment(d, building_kind=building_kind, roof_kind=roof_kind)
    use_pack = bool(d.treatment_setup)
    r["errors"] = validate(d)
    if r["errors"]:
        r["status"] = "invalid"
        return r
    needed = {
        "pump_flow_lps": "одновременный расход полива, не суточный объём",
        "pump_geometric_head_m": "подъём от минимального уровня воды до потребителя",
        "pump_terminal_head_m": "напор у поливочного устройства по его паспорту",
        "pump_network_loss_m": "потери труб и арматуры, без шланга и очистки",
        "pump_treatment_loss_m": "потери подготовки и обеззараживания",
        "pump_loss_source": "источник расчёта потерь и характеристик потребителя",
        "pump_min_submergence_m": "минимальное погружение водозаборной части",
        "pump_max_submergence_m": "максимальная глубина погружения",
        "pump_temperature_c": "температура перекачиваемой воды",
        "pump_pipe_inner_mm": "внутренний диаметр напорной магистрали",
        "pump_clean_water": "подтверждение пригодности подготовленной воды для насоса",
        "outlets_count": "количество точек полива", "hose_choice": "шланг либо стационарная сеть",
    }
    if use_pack:
        # An old aggregate must not mask absent/stale component losses.
        needed.pop("pump_treatment_loss_m")
    if d.hose_choice == "custom":
        needed.update(hose_model="модель и паспорт шланга", hose_length_m="длина одного шланга",
                      hose_inner_mm="внутренний диаметр шланга", hose_pn_bar="рабочее давление шланга",
                      hose_loss_m="потери в диктующем шланге при его расходе", hose_sets="число комплектов шланга")
    r["missing"] = [title for key, title in needed.items() if getattr(d, key) in (None, "")]
    if use_pack and not treatment["ready_for_pump"]:
        r["missing"].extend(treatment["missing"])
        r["errors"].extend(treatment["errors"])
        if not r["missing"] and not r["errors"]:
            r["missing"].append("завершённая проверка типовой подготовки дождевой воды")
    if d.purpose != "irrigation":
        r["errors"].append("Эта обвязка предназначена для полива. Для смыва и иных технических нужд требуется отдельная схема.")
    if d.pump_clean_water == "no":
        r["errors"].append("Насосы каталога предназначены для чистой воды. Подготовка дождевого стока не подтверждена.")
    if d.pump_pipe_inner_mm is not None and d.pump_pipe_inner_mm < 25:
        r["errors"].append("Паспорт ВОДОМЕТ запрещает внутренний диаметр напорной магистрали менее 25 мм.")
    if d.pump_min_submergence_m is not None and d.pump_min_submergence_m < 0.3:
        r["errors"].append("Для этой проверки требуется не менее 0,30 м погружения водозабора; поплавок должен отключать насос до осушения.")
    if d.pump_max_submergence_m is not None and d.pump_max_submergence_m > 30:
        r["errors"].append("Погружение превышает паспортные 30 м.")
    if d.pump_min_submergence_m is not None and d.pump_max_submergence_m is not None and d.pump_min_submergence_m > d.pump_max_submergence_m:
        r["errors"].append("Минимальное погружение больше максимального.")
    if d.pump_temperature_c is not None and not 1 <= d.pump_temperature_c <= 35:
        r["errors"].append("Температура вне паспортного диапазона +1…+35 °C.")
    if d.hose_choice == "custom" and d.hose_sets and d.outlets_count and d.hose_sets > d.outlets_count:
        r["errors"].append("Комплектов шланга больше точек полива: уточните состав, запасные комплекты здесь не учитываются.")
    if r["missing"] or r["errors"]:
        r["status"] = "invalid" if r["errors"] else "needs_data"
        return r
    if d.pump_min_submergence_m <= 1:
        r["pending"].append("При погружении до 1 м паспорт требует обратный клапан на расстоянии 1–7 м от выхода насоса, чтобы избежать воздушной пробки; расположение проверить при компоновке бака.")
    hose_loss = d.hose_loss_m if d.hose_choice == "custom" else 0.0
    treatment_loss = treatment["head_loss_m"] if use_pack else d.pump_treatment_loss_m
    losses = d.pump_network_loss_m + treatment_loss + hose_loss
    h = max(0.0, d.pump_geometric_head_m + d.pump_terminal_head_m + losses)
    q = d.pump_flow_lps * 3.6
    r["duty"] = dict(q_m3h=q, h_m=h, geometric_m=d.pump_geometric_head_m,
                     terminal_m=d.pump_terminal_head_m, network_m=d.pump_network_loss_m,
                     treatment_m=treatment_loss, hose_m=hose_loss)
    if h == 0:
        r["status"] = "not_required"
        return r
    for pump in CATALOG:
        nominal = interpolate_head(pump["curve"], q)
        # The published graph was digitized, not a laboratory acceptance curve.
        # Explicit conservative screen for the manufacturer's +/-15% tolerance.
        lower = nominal * 0.85 if nominal is not None else None
        max_pressure = (pump["shutoff_head_m"] * 1.15 + d.pump_max_submergence_m) * 9.80665 / 100
        hose_ok = d.hose_choice == "none" or d.hose_pn_bar >= max_pressure
        reasons = []
        if nominal is None:
            reasons.append("Расход вне проверенного диапазона 3–50 л/мин; экстраполяция запрещена.")
        elif lower < h:
            reasons.append("Недостаточен напор с учётом паспортного допуска 15%.")
        if not hose_ok:
            reasons.append("Рабочее давление шланга ниже проверочного давления при закрытом выходе.")
        if use_pack:
            for item in treatment["candidates"]:
                if max_pressure > item["pressure_screen_bar"]:
                    reasons.append(f"{item['model']}: проверочное давление выше ограничения оборудования подготовки.")
        r["candidates"].append({**pump, "nominal_head_m": nominal, "lower_head_m": lower,
                                "pressure_check_bar": max_pressure, "reasons": reasons,
                                "admitted": not reasons})
    r["selected"] = next((p for p in r["candidates"] if p["admitted"]), None)
    r["status"] = "preliminary" if r["selected"] else "no_match"
    return r
