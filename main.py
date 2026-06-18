import os
from dotenv import load_dotenv

load_dotenv()

from helpers.otel_env import normalize_otlp_endpoint_env

normalize_otlp_endpoint_env()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from contextlib import asynccontextmanager

# Import all routers
from app.routers import chat, transcribe, suggestions, tts, health, openai_compat, token

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events for startup and shutdown"""
    # Startup
    print(f"🚀 {settings.app_name} starting up...")
    print(f"📍 Environment: {settings.environment}")
    print(f"🔧 Debug mode: {settings.debug}")
    print(f"🌐 CORS origins: {settings.allowed_origins}")
    yield
    # Shutdown
    print(f"🛑 {settings.app_name} shutting down...")

# Create FastAPI app with settings
app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    description="AI-powered Voice Assistant API for Agricultural Support",
    lifespan=lifespan
)

# Add CORS middleware with enhanced settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.allowed_credentials,
    allow_methods=settings.allowed_methods,
    allow_headers=settings.allowed_headers,
)


@app.get("/")
async def root():
    """Root endpoint with app information"""
    return {
        "app": settings.app_name,
        "environment": settings.environment,
        "debug": settings.debug,
        "api_prefix": settings.api_prefix
    }

# Include all routers with API prefix from settings
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(transcribe.router, prefix=settings.api_prefix)
app.include_router(suggestions.router, prefix=settings.api_prefix)
app.include_router(tts.router, prefix=settings.api_prefix)
app.include_router(health.router, prefix=settings.api_prefix) 

# OpenAI-compatible endpoints (do not depend on settings.api_prefix)
app.include_router(openai_compat.router, prefix="/api/v1")

# Local/sandbox token minting (/api/token). Disable with ENABLE_TOKEN_MINT=false
# once a real auth/SSO provider issues the token. See OAN_HOSTING_PLAN.md.
if os.getenv("ENABLE_TOKEN_MINT", "true").lower() in {"1", "true", "yes"}:
    app.include_router(token.router, prefix=settings.api_prefix)