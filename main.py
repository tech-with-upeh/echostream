from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import auth, gifts, live, payments, prefrences, subscription_changes, voice, wstts
import app.models

Path("uploads/gift-alerts").mkdir(parents=True, exist_ok=True)

app = FastAPI(title="EchoStream Backend API")

app.include_router(auth.router)
app.include_router(voice.router)
app.include_router(wstts.router)
app.include_router(live.router)
app.include_router(prefrences.router)
app.include_router(gifts.router)
app.include_router(payments.router)
app.include_router(subscription_changes.router)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
def health_check():
    return {"status": "healthy"}
