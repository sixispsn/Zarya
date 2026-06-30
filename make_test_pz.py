"""
Тестовая генерация ПЗ на данных Нахабино.
Запуск: python make_test_pz.py
"""
from app.pz.generator import generate_pz_pdf, generate_spec_pdf
from app.pz.project import (
    BuildingFlags,
    BuildingPurpose,
    DocumentInfo,
    FireSystem,
    FlowsData,
    HwsType,
    PipeMaterials,
    Project,
    Stage,
    WaterSource,
    FixtureGroup,
)

# Расчётное ядро + мост + расчёт напора
from app.calc.pumps import PumpInput, calculate_pump
from app.calc.water_meters import MeterInput, calculate_meters
from app.pz.flows_bridge import pump_from_calc, meters_from_calc
from app.pz.rules import calc_required_head

# Данные объекта Нахабино (кинозал + кафе на 262 места)
project = Project(
    document=DocumentInfo(
        cipher="3010-713-2025-ИОС2",
        object_name="Капитальный ремонт помещений кинозала и кафе на 262 места, 2 эт., ~1800 м²",
        object_part="Кинозал и кафе",
        object_address="пос. Нахабино",
        organization="ООО «Индеком»",
        developer_name="Пашкевич А.",
        inspector_name="Терашкевич А.",
        stage=Stage.P,
    ),
    building=BuildingFlags(
        purpose=BuildingPurpose.PUBLIC,
        floors_above=2,
        height_m=10.0,
        total_area_m2=1800.0,   # общая площадь (для удельного расчёта труб)
        hws_type=HwsType.CENTRAL,   # ГВС готовое из внешней котельной (вне нашего раздела)
        seats=262,
        fire_class="Ф2.1",
        risers_v1=4, risers_t3=4, risers_t4=2,
    ),
    source=WaterSource(
        description="от существующей городской сети водоснабжения",
        guaranteed_head_m=25.0,     # Hгар из ТУ заказчика (тест)
        # --- слагаемые Hтр (формула 14, п.8.27) ---
        elev_header_m=-2.5,         # ось напорного коллектора насоса в подвале, м
        elev_fixture_m=6.5,         # излив диктующего прибора (2 эт.), м  -> Hgeom=9.0
        il_dict_m=4.0,              # линейные потери i·l по диктующему направлению, м
        network_kind="domestic",    # kм=0,3 (хоз-питьевая сеть общественного здания)
        h_pr_m=20.0,                # Hпр (п.8.21)
        h_tepl_m=0.0,               # Hтепл=0: ГВС готовое из внешней котельной
        il_vvod_m=1.5,              # линейные потери i·l ввода, м  -> Hlввод=1,65
    ),
    materials=PipeMaterials(),
    flows=FlowsData(
        q_day_tot=5.76, q_day_c=3.6, q_day_h=2.16,
        q_sec_tot=1.499, q_sec_c=0.933, q_sec_h=0.774,
        q_hr_tot=3.182, q_hr_c=1.941, q_hr_h=1.547,
        sewage_l_per_s=3.099, heat_max_kw=107.7,   # тепловая нагрузка ГВС — для котельной/смежников
    ),
    fire=FireSystem(required=True, streams=2, q_per_stream=2.6, q_total=5.2,
                    pk_total=4, nozzle_dn=50, hose_length_m=20),
    # Приборы по заданию АР (тест) — для арматуры спецификации
    fixtures=[
        FixtureGroup('Унитаз', 8),
        FixtureGroup('Писсуар', 4),
        FixtureGroup('Умывальник', 10),
        FixtureGroup('Мойка кухонная', 3, valve_dn=20),
        FixtureGroup('Раковина хозяйственная (видуар)', 2),
    ],
)

# --- Подбор счётчиков -> project.meters (таблица 5.1.13) ---
meter_res = calculate_meters(MeterInput(
    hws_type="central",
    period_hours=24.0,
    q_fire_l_per_s=project.fire.q_total,
    inputs_count=1,
    q_sec_tot=project.flows.q_sec_tot,
    q_sec_c=project.flows.q_sec_c,
    q_sec_h=project.flows.q_sec_h,
    q_day_tot=project.flows.q_day_tot,
    q_day_c=project.flows.q_day_c,
    q_day_h=project.flows.q_day_h,
    q_hr_c=project.flows.q_hr_c,
    q_hr_h=project.flows.q_hr_h,
))
project.meters = meters_from_calc(meter_res)

# --- Требуемый напор Hтр (потери счётчика ХВС идут в ∑Hвод) ---
def _cold_loss(m):
    for r in m.rows:
        if "ввод" in r.label.lower():
            return r.h_a
    for r in m.rows:
        if "хвс" in r.label.lower() or "холодн" in r.label.lower():
            return r.h_a
    return None

head = calc_required_head(project.source, h_vod_m=_cold_loss(project.meters))
print(f"Hтр = {head.h_required_m} м; Hгар = {head.h_guaranteed_m} м; "
      f"насос нужен: {head.pump_needed}; Hнас = {head.h_pump_m} м")

# --- Подбор насоса ОТ ТОГО ЖЕ Hтр (таблица 5.1.8 + график Q-H) ---
if head.pump_needed:
    pump_res = calculate_pump(PumpInput(
        q_design_m3h=round(project.flows.q_sec_c * 3.6, 2),  # холодная система, макс. секундный -> м³/ч
        pump_type="boost",
        mode="1",
        h_geom_manual=head.h_geom_m,        # та же геометрия, что в Hтр
        h_losses=head.h_losses_dynamic_m,   # ∑Hil+∑Hвод+Hтепл+Hlввод
        h_pr=head.h_pr_m,                   # Hпр=20
        h_gar=head.h_guaranteed_m or 0.0,   # Hгар из ТУ
        npsh_a=8.0,
    ))
    if pump_res.candidates:
        project.pumps = pump_from_calc(
            pump_res,
            purpose="повышение давления хозяйственно-питьевого водопровода",
            type_label="хозяйственно-питьевой",
            scheme_note="1 раб. + 1 рез.",
            mode="1",
        )

out = generate_pz_pdf(project, "/tmp/pz_nahabino.pdf")
print(f"PDF создан: {out}")
print("Открой командой: open /tmp/pz_nahabino.pdf")

spec_out = generate_spec_pdf(project, "/tmp/spec_nahabino.pdf")
print(f"Спецификация создана: {spec_out}")
print("Открой командой: open /tmp/spec_nahabino.pdf")

from app.pz.scheme import generate_scheme_svg
generate_scheme_svg(project, "/tmp/scheme_nahabino.svg")
print("Схема создана: /tmp/scheme_nahabino.svg")
