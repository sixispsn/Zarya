"""Вход предпросмотра изменений проекта без сохранения."""
from typing import Optional

from pydantic import BaseModel, Field


class ImpactPreviewInput(BaseModel):
    consumer_counts: Optional[list[int]] = None
    floors: Optional[int] = Field(default=None, gt=0, le=300)
    building_height_m: Optional[float] = Field(default=None, gt=0, le=1000)
    fire_height_m: Optional[float] = Field(default=None, gt=0, le=1000)
    guaranteed_head_m: Optional[float] = Field(default=None, ge=0, le=1000)
