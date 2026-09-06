from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ai import router as ai_router
from app.api.analysis import router as analysis_router
from app.api.companies import router as companies_router
from app.api.crawl import router as crawl_router
from app.api.daily import router as daily_router
from app.api.economy_analysis import router as economy_analysis_router
from app.api.ecosystem import router as ecosystem_router
from app.api.jobs import router as jobs_router
from app.api.recommendations import router as recommendations_router
from app.api.resumes import router as resumes_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)
app.include_router(ai_router)
app.include_router(analysis_router)
app.include_router(economy_analysis_router)
app.include_router(companies_router)
app.include_router(crawl_router)
app.include_router(daily_router)
app.include_router(ecosystem_router)
app.include_router(jobs_router)
app.include_router(recommendations_router)
app.include_router(resumes_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}
