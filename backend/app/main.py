from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes import zones as zones_routes


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
