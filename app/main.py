"""
Заря — инженерный калькулятор ВК.
Точка входа FastAPI приложения.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import irrigation, storm, water_demand, water_meters

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
@app.get("/")
def root():
    """Проверка что сервер работает."""
    return {
        "service": "Заря",
        "version": "0.1.0",
        "status": "ok",
    }


@app.get("/health")
def health():
    """Healthcheck для мониторинга."""
    return {"status": "healthy"}