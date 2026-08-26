from fastapi import FastAPI

from app.database import Base, engine
from app.routers import auth, live, payments, prefrences, subscription_changes, voice, wstts
import app.models

# Automatically create tables on local start.
# Run scripts/migrate_fish_audio.sql against existing production databases.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="EchoStream Backend API")

app.include_router(auth.router)
app.include_router(voice.router)
app.include_router(wstts.router)
app.include_router(live.router)
app.include_router(prefrences.router)
app.include_router(payments.router)
app.include_router(subscription_changes.router)


@app.get("/")
def health_check():
    return {"status": "healthy"}
