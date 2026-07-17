"""
Pydantic-схемы для API расчёта ВПВ.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class FireRequest(BaseModel):
    """Входные данные расчёта ВПВ."""
    building_type: Literal[
        "f13", "f12_hotel", "f12_hostel", "f11",
        "f21_theater", "f21_lib", "f22", "f_office", "f5",
    ] = Field(..., description="Тип здания по СП 10")
    floors: int = Field(default=1, ge=1, le=100, description="Этажность")
    height_m: Optional[float] = Field(default=None, gt=0, description="Высота здания, м")
    corridor_length_m: Optional[float] = Field(default=None, ge=0, description="Длина коридора (Ф1.3), м")
    seats: Optional[int] = Field(default=None, ge=0, description="Вместимость зала (Ф2.1 театры)")
    area_m2: Optional[float] = Field(default=None, ge=0, description="Площадь (Ф2.1 библ./Ф2.2), м²")
    fire_degree: Literal["I_II", "III", "IV", "V"] = Field(default="I_II", description="Степень огнестойкости")
    category: Literal["AB", "V", "GD"] = Field(default="V", description="Категория пож. опасности")
    construction_class: Literal["C0", "C1", "C2", "C3"] = Field(default="C0", description="Класс констр. опасности")
    volume_thousand_m3: float = Field(default=5.0, ge=0, description="Объём здания, тыс. м³")
    dn: Literal[50, 65] = Field(default=50, description="Диаметр клапана ПК")
    nozzle_mm: Literal[13, 16, 19] = Field(default=13, description="Диаметр ствола, мм")
    hose_m: Literal[10, 15, 20] = Field(default=20, description="Длина рукава, м")
    jet_m: int = Field(default=12, ge=6, le=20, description="Высота струи, м")


class FireResponse(BaseModel):
    """Результат расчёта ВПВ."""
    required: bool = Field(..., description="Требуется ли ВПВ")
    streams: int = Field(..., description="Число струй n")
    q_per_stream: float = Field(..., description="Расход диктующего ПК, л/с")
    q_total: float = Field(..., description="Q_пож = n × q, л/с")
    pressure_mpa: Optional[float] = Field(None, description="Давление у клапана, МПа")
    table_used: str = Field(..., description="Использованная таблица (7.1 / 7.2)")
    nozzle_found: bool = Field(..., description="Найдена ли комбинация в табл. 7.3")
    pressure_control_required: bool = Field(
        ..., description="Нужна диафрагма/регулятор при давлении более 0,45 МПа",
    )
    message: str = Field(..., description="Пояснение")
