from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import APP_NAME, APP_ENV
from auth.routes import router as auth_router
from invoice.routes import router as invoice_router


# =========================================================
# CLAIMGUARD APPLICATION
# =========================================================

app = FastAPI(
    title=APP_NAME,
    description=(
        "ClaimGuard - Intelligent Invoice "
        "Verification & Anomaly Detection System"
    ),
    version="1.0.0",
)


# =========================================================
# CORS CONFIGURATION
# =========================================================
# Development stage:
# Frontend and backend are running on different ports.
#
# Frontend:
# http://127.0.0.1:5500
#
# Backend:
# http://127.0.0.1:8000
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Development only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# AUTHENTICATION ROUTES
# =========================================================

app.include_router(auth_router)
app.include_router(invoice_router)


# =========================================================
# ROOT ENDPOINT
# =========================================================

@app.get("/")
def root():
    return {
        "message": "ClaimGuard API is running",
        "environment": APP_ENV,
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "ClaimGuard Backend",
    }