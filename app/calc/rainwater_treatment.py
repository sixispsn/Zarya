"""Explicit, limited extension for a residential hard-surface roof terrace.

This is a process/candidate check, not a legacy algorithm or chemical model.
Supplier head losses are added only at the flow stated in the selection sheet.
No extrapolation, inferred quality, dosing or automatic bypass to K1/V1.
"""
from copy import deepcopy
import math

from app.data.rainwater_treatment import CATALOG, PACK_ID, PACK_LABEL

SETUPS = {PACK_ID: PACK_LABEL}
SURFACES = {"hard_terrace": "Обычная терраса · твёрдое покрытие",
            "other": "Грунт, парковка, смешанный или другой водосбор"}
NUMBERS = {"treatment_selection_flow_lps": False,
           "treatment_filter_loss_m": True, "treatment_uv_loss_m": True}
TEXTS = ("treatment_selection_source", "treatment_quality_basis")
PROCESS = (
    "Кровля: решётка / задержание крупного мусора",
    "Отведение первого загрязнённого стока",
    "Отстаивание и накопление с удалением осадка",
    "Погружной насос подготовленной воды",
    "Картриджная фильтрация и контроль перепада давления",
    "УФ-обеззараживание с контролем дозы / расхода",
    "Отсечка при отказе обработки → отдельная сеть полива",
)
PENDING = (
    "Материал покрытия и загрязнения: исключить сток с грунтом, парковок, бытовые стоки и моющие растворы. По городу состав не назначается.",
    "Исходное и требуемое качество, применимость фильтра и режим УФ (доза, УФ-пропускание, температура, проток) — по обоснованию и листу подбора изготовителя.",
    "Потери фильтра при принятом загрязнении и УФ при расчётном расходе. Паспортный максимум расхода не доказывает пригодность.",
    "Первый сток, пиковый пропуск К2, отстойная зона, удаление осадка и безопасный перелив — отдельно; суточный баланс их не рассчитывает.",
    "Запрет подачи при отказе УФ, недостаточной дозе, превышении расхода, недопустимом качестве и загрязнении фильтра; без байпаса неочищенной воды.",
    "Срок хранения, чистка и дезинфекция, защита от замерзания, отсутствие контакта технической воды с людьми; не питьё и не полив пищевых культур.",
)


def project_context(project):
    return dict(building_kind=getattr(project.building.purpose, "value", project.building.purpose),
                roof_kind=project.sewage.roof_kind)


def validate(d):
    errors = []
    for key, options in (("treatment_setup", SETUPS), ("treatment_surface", SURFACES)):
        value = getattr(d, key)
        if not isinstance(value, str) or value not in {"", *options}:
            errors.append(f"Подготовка дождевой воды: неизвестное {key}.")
    for key, zero in NUMBERS.items():
        value = getattr(d, key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)
                                  or value > 1e6 or value < 0 or (not zero and value == 0)):
            errors.append(f"Подготовка дождевой воды: некорректное {key}.")
    for key in TEXTS:
        if not isinstance(getattr(d, key), str) or len(getattr(d, key)) > 200:
            errors.append(f"{key}: текст до 200 символов.")
    return errors


def assess_treatment(d, *, building_kind=None, roof_kind=None):
    r = dict(status="not_configured", label=PACK_LABEL, missing=[], errors=[],
             candidates=[], head_loss_m=None, ready_for_pump=False,
             process=list(PROCESS), pending=list(PENDING), quality_verified=False)
    if not d.enabled or not d.treatment_setup:
        return r
    r["errors"] = validate(d)
    if r["errors"]:
        r["status"] = "invalid"
        return r
    if not building_kind:
        r["missing"].append("назначение здания")
    elif building_kind != "residential":
        r["errors"].append("Типовой комплект ограничен жилым зданием.")
    if roof_kind in (None, "", "unknown", "flat"):
        r["missing"].append("подтверждённый вид кровли")
    elif roof_kind != "flat_accessible":
        r["errors"].append("Этот комплект предназначен для плоской эксплуатируемой кровли.")
    if not d.treatment_surface:
        r["missing"].append("обычная терраса с твёрдым покрытием")
    elif d.treatment_surface != "hard_terrace":
        r["errors"].append("Этот водосбор вне первой версии типовой подготовки; данные сохранены.")
    if d.purpose != "irrigation":
        r["errors"].append("Комплект предназначен только для полива декоративного озеленения.")
    if r["errors"]:
        r["status"] = "out_of_scope"
        return r
    if r["missing"]:
        r["status"] = "needs_data"
        return r
    r["candidates"] = deepcopy(list(CATALOG))
    q = d.pump_flow_lps
    if type(q) not in (int, float) or not math.isfinite(q) or q <= 0:
        r["missing"].append("одновременный расход полива")
        q = None
    for c in r["candidates"]:
        c["reasons"] = []
        if q is not None and q * 3.6 > c["screening_flow_max_m3h"] + 1e-9:
            c["reasons"].append("Расход превышает даже верхнюю каталожную границу. Параллельные установки автоматически не добавляются.")
        t = d.pump_temperature_c
        if type(t) in (int, float) and math.isfinite(t):
            if ((c["temperature_min_c"] is not None and t < c["temperature_min_c"])
                    or (c["temperature_max_c"] is not None and t > c["temperature_max_c"])):
                c["reasons"].append("Температура воды вне паспортного диапазона.")
        c["screen_passed"] = not c["reasons"]
        r["errors"].extend(f"{c['model']}: {msg}" for msg in c["reasons"])
    for key, title in (
        ("treatment_selection_flow_lps", "расход, на который выдан лист подбора"),
        ("treatment_filter_loss_m", "потери фильтра с учётом загрязнения"),
        ("treatment_uv_loss_m", "потери УФ-установки"),
        ("treatment_selection_source", "лист подбора обоих изделий: расход, потери и условия эксплуатации"),
        ("treatment_quality_basis", "обоснование исходного и требуемого качества воды для этих изделий"),
    ):
        if getattr(d, key) is None or (isinstance(getattr(d, key), str) and not getattr(d, key).strip()):
            r["missing"].append(title)
    if q is not None and d.treatment_selection_flow_lps is not None and not math.isclose(q, d.treatment_selection_flow_lps, rel_tol=1e-9, abs_tol=1e-12):
        r["missing"].append("обновлённый лист подбора: расход изменился, прежние потери не применяются")
    if r["errors"]:
        r["status"] = "no_match"
    elif r["missing"]:
        r["status"] = "needs_data"
    else:
        r.update(status="preliminary", ready_for_pump=True,
                 head_loss_m=d.treatment_filter_loss_m + d.treatment_uv_loss_m)
    return r
