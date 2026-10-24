"""api/ — Application FastAPI du dashboard (assemblage des routeurs)."""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from utils.logger import logger
from api.routers import forex_v1, copytrading, settings as settings_router, forex_v2

app = FastAPI(
    title="Dashboard trading — forex",
    description="Suivi du paper trading forex multi-signaux.",
    version="2.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Capture toute exception non gérée pour éviter que le serveur ne crashe."""
    logger.error(f"💥 Exception non gérée: {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={
        "status": "error", "message": "Erreur interne du serveur", "detail": str(exc)})


@app.get("/health")
async def health_check():
    """Health check — vérifie que le serveur est opérationnel."""
    return {"status": "ok", "service": "trading-dashboard", "modules": ["forex"]}


app.include_router(forex_v1.router)
app.include_router(copytrading.router)
app.include_router(settings_router.router)
app.include_router(forex_v2.router)
app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")
