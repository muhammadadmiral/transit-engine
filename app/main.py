from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.core.config import get_settings
from app.routers import data_refresh, geocode, health, network, route_search, stops

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(health.router)
app.include_router(route_search.router)
app.include_router(data_refresh.router)
app.include_router(stops.router)
app.include_router(network.router)
app.include_router(geocode.router)
