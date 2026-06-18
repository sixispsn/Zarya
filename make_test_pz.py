"""
Тестовая генерация ПЗ на данных Нахабино.
Запуск: python make_test_pz.py
"""
from app.pz.generator import generate_pz_pdf
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
)

# Расчётное ядро + мост в модель ПЗ
from app.calc.pumps import PumpInput, calculate_pump
from app.calc.water_meters import MeterInput, calculate_meters
from app.pz.flows_bridge import pump_from_calc, meters_from_calc

# Данные объекта Нахабино (кинозал + кафе на 262 места)
project = Project(
    document=DocumentInfo(
        cipher="3010-713-2025-ИОС2",
        object_name="Многофункциональный зал (кинозал) и кафе на 262 места",
        object_address="пос. Нахабино",
        stage=Stage.P,
    ),
    building=BuildingFlags(
        purpose=BuildingPurpose.PUBLIC,
        floors_above=2,
        height_m=10.0,
        hws_type=HwsType.CENTRAL,
        seats=262,
        fire_class="Ф2.1",
    ),
    source=WaterSource(
        description="от существующей городской сети водоснабжения",
        guaranteed_head_m=10.0,  # ТЕСТ: чтобы сработал подбор насоса; в реале было None
    ),
    materials=PipeMaterials(),  # дефолтные материалы (сталь + PE-X)
    flows=FlowsData(
        q_day_tot=5.76, q_day_c=3.6, q_day_h=2.16,
        q_sec_tot=1.499, q_sec_c=0.933, q_sec_h=0.774,
        q_hr_tot=3.182, q_hr_c=1.941, q_hr_h=1.547,
        sewage_l_per_s=3.099, heat_max_kw=107.7,
    ),
    fire=FireSystem(required=True, streams=2, q_per_stream=2.6, q_total=5.2),
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

# --- Подбор насоса -> project.pumps (таблица 5.1.8 + график Q-H) ---
pump_res = calculate_pump(PumpInput(
    q_design_m3h=round(project.flows.q_sec_tot * 3.6, 2),  # макс. секундный -> м³/ч
    pump_type="boost",
    mode="1",
    floors=project.building.floors_above,
    floor_height=3.0,
    h_losses=5.0,
    h_pr=20.0,
    h_gar=project.source.guaranteed_head_m or 0.0,
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
