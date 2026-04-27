"""
FastAPI main application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .routes import auth as auth_router
from .routes import admin as admin_router
from .routes import billing as billing_router
from .routes import files
from .routes import generate
from .routes import chat as chat_router
from .routes import github as github_router
from .routes import projects
from .routes import providers
from .routes import settings as settings_router
from .routes import users as users_router
from . import db  # Ensure DB is initialized on startup

app = FastAPI(
    title="WAGI — AI Website Builder",
    description="Full-stack React+Vite+Express project generator powered by LLMs",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, same_site="lax")

# Routers — existing
app.include_router(generate.router)
app.include_router(chat_router.router)
app.include_router(files.router)
app.include_router(settings_router.router)
app.include_router(providers.router)
app.include_router(projects.router)
app.include_router(github_router.router)

# Routers — platform features
app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(admin_router.router)
app.include_router(billing_router.router)


@app.on_event("startup")
async def verify_database_connection():
    db.ensure_db_ready()


@app.get("/")
async def root():
    return {
        "name": "WAGI API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "database": "connected"}
