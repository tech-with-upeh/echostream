from fastapi import FastAPI
from app.database import engine, Base
from app.routers import auth, voice, payments
import app.models

# Automatically create tables on local start.
# Replace with Alembic migrations before production deployment.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="EchoStream Backend API")

app.include_router(auth.router)
app.include_router(voice.router)
app.include_router(payments.router)


@app.get("/")
def health_check():
    return {"status": "healthy"}
