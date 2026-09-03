"""Заря — инженерный калькулятор ВК. Точка входа FastAPI приложения."""
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    fire,
    insulation,
    irrigation,
    preflight,
    pumps,
    storm,
    water_demand,
    water_meters,
)
from app.normative.radar import run_radar_check
from app.web import (
    architecture_import,
    normative_radar,
    passport,
    reference_analysis,
    wizard,
)


logger = logging.getLogger(__name__)


def _positive_seconds(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        logger.warning("Некорректное значение %s; используется %s", name, default)
        return default
    return max(minimum, value)


async def _normative_monitor_loop() -> None:
    initial_delay = _positive_seconds(
        "ZARYA_NORMATIVE_MONITOR_INITIAL_DELAY_SECONDS",
        30,
    )
    interval = _positive_seconds(
        "ZARYA_NORMATIVE_MONITOR_INTERVAL_SECONDS",
        21_600,
        minimum=3_600,
    )
    await asyncio.sleep(initial_delay)
    while True:
        try:
            await asyncio.to_thread(run_radar_check)
        except Exception:  # Фоновый контроль не должен останавливать приложение.
            logger.exception("Не выполнен фоновый проход нормативного радара")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    monitor_task: asyncio.Task | None = None
    if os.environ.get("ZARYA_NORMATIVE_MONITOR_ENABLED", "0") == "1":
        monitor_task = asyncio.create_task(_normative_monitor_loop())
    try:
        yield
    finally:
        if monitor_task is not None:
            monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await monitor_task

app = FastAPI(
    title="Заря API",
    description="Расчёты внутреннего водоснабжения и канализации по СП 30.13330.2020",
    version="0.6.1",
    lifespan=lifespan,
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
app.include_router(architecture_import.router)
app.include_router(reference_analysis.router)
app.include_router(normative_radar.router)
app.include_router(passport.router)
app.include_router(insulation.router)
app.include_router(pumps.router)
app.include_router(preflight.router)
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
