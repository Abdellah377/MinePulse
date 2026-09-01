from fastapi import APIRouter

from app.api.routes import actions, ai, alerts, bootstrap, equipment, external_context, oem, operations, optimization, production, settings, simulation, timeline, zones

api_router = APIRouter(prefix="/api")

api_router.include_router(bootstrap.router, tags=["bootstrap"])
api_router.include_router(timeline.router, tags=["timeline"])
api_router.include_router(equipment.router, prefix="/equipment", tags=["equipment"])
api_router.include_router(zones.router, prefix="/zones", tags=["zones"])
api_router.include_router(zones.roads_router, prefix="/roads", tags=["roads"])
api_router.include_router(operations.router, tags=["operations"])
api_router.include_router(production.router, prefix="/production", tags=["production"])
api_router.include_router(simulation.router, prefix="/simulation", tags=["simulation"])
api_router.include_router(oem.router, prefix="/oem", tags=["oem"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai-investigations"])
api_router.include_router(actions.router, prefix="/actions", tags=["actions-inbox"])
api_router.include_router(optimization.router, prefix="/optimization", tags=["optimization"])
api_router.include_router(external_context.router, prefix="/external-context", tags=["external-context"])
