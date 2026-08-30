from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.routes import zones as zones_routes
from app.services.operational.clock import OperationalClockUnavailable
from simulator.file_io import RuntimeFileError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.monitoring.scheduler import get_monitoring_scheduler
    from simulator.service import get_simulation_service

    svc = get_simulation_service()
    monitor = get_monitoring_scheduler()
    try:
        svc.ensure_started()
    except Exception:
        # API still serves; Simulation Centre shows engine offline + error
        pass
    await monitor.start()
    try:
        yield
    finally:
        await monitor.stop()
        svc.stop()


app = FastAPI(title="MinePulse API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(OperationalClockUnavailable)
@app.exception_handler(RuntimeFileError)
async def runtime_unavailable(request: Request, exc: Exception):
    logger.error("Runtime state unavailable for %s", request.url.path,
                 exc_info=(type(exc), exc, exc.__traceback__))
    clock_error = isinstance(exc, OperationalClockUnavailable)
    return JSONResponse(status_code=503, content={"detail": {
        "code": "OPERATIONAL_CLOCK_UNAVAILABLE" if clock_error else "SIMULATION_STATE_UNAVAILABLE",
        "message": "Horloge opérationnelle indisponible." if clock_error else "État du simulateur indisponible.",
    }})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(zones_routes.events_router, prefix="/api", tags=["events"])


@app.get("/health")
def health():
    from simulator.service import get_simulation_service

    svc = get_simulation_service()
    return {
        "status": "ok",
        "simulator": {
            "embedded": True,
            "tick_thread_alive": svc.running,
            "last_error": svc.last_error,
        },
    }
