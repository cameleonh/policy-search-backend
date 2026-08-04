from fastapi import FastAPI

from apps.api.routers import health

app = FastAPI(
    title="Policy Search API",
    description="Unified youth and small-business policy search API",
    version="0.0.0",
)

app.include_router(health.router)
