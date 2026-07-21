"""Заря — инженерный калькулятор ВК. Точка входа FastAPI приложения."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import fire, insulation, irrigation, pumps, storm, water_demand, water_meters
from app.web import wizard

app = FastAPI(
    title="Заря API",
    description="Расчёты внутреннего водоснабжения и канализации по СП 30.13330.2020",
    version="0.1.0",
)

# CORS — разрешаем фронтенду обращаться к API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(water_demand.router)
app.include_router(irrigation.router)
app.include_router(storm.router)
app.include_router(water_meters.router)
app.include_router(fire.router)
app.include_router(wizard.router)
app.include_router(insulation.router)
app.include_router(pumps.router)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "web" / "static")),
    name="static",
)

@app.get("/")
def root():
    """Основная точка входа — рабочее место проектировщика."""
    return RedirectResponse(url="/wizard", status_code=307)


@app.get("/health")
def health():
    """Healthcheck для мониторинга."""
    return {"status": "healthy"}
