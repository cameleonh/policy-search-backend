import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import health, search

app = FastAPI(
    title="Policy Search API",
    description="Unified youth and small-business policy search API",
    version="0.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(search.router)
