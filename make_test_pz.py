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
        guaranteed_head_m=None,  # оставим плашку — проверим жёлтое поле
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

out = generate_pz_pdf(project, "/tmp/pz_nahabino.pdf")
print(f"PDF создан: {out}")
print("Открой командой: open /tmp/pz_nahabino.pdf")