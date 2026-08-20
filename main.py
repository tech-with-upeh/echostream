from fastapi import FastAPI
from app.database import engine, Base
from app.routers import auth, voice, wstts, live, prefrences
import app.models 
# Automatically migrate tables on local start
Base.metadata.create_all(bind=engine)

app = FastAPI(title="EchoStream Backend API")

# Include the partitioned router paths
app.include_router(auth.router)
app.include_router(voice.router)
app.include_router(wstts.router)
app.include_router(live.router)
app.include_router(prefrences.router)

@app.get("/")
def health_check():
    return {"status": "healthy"}
