import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from routers import submission
from routers import domains
from routers import admin
from routers import assessment
from routers import coding
from routers import coding_admin
from routers import auth

app = FastAPI(
    title="DSC Recruitment Platform API",
    description="Backend API for code submission and evaluation",
    version="1.0.0",
)

# Configure CORS from environment variable
cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
cors_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(submission.router)
app.include_router(domains.router, tags=["Domains"])
app.include_router(admin.router)
app.include_router(assessment.router)
app.include_router(coding.router)
app.include_router(coding_admin.router)


@app.get("/")
def root():
    """Health check endpoint"""
    return {"status": "Healthy", "message": "API is working"}


if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)
