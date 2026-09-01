import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import auth, gifts, live, payments, prefrences, subscription_changes, voice, wstts, sounds
from app.gift_catalog import gift_catalog_scheduler
import app.models


@asynccontextmanager
async def lifespan(app: FastAPI):
    gift_sync_task = asyncio.create_task(gift_catalog_scheduler())
    try:
        yield
    finally:
        gift_sync_task.cancel()
        await asyncio.gather(gift_sync_task, return_exceptions=True)


app = FastAPI(title="EchoStream Backend API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(voice.router)
app.include_router(wstts.router)
app.include_router(live.router)
app.include_router(prefrences.router)
app.include_router(gifts.router)
app.include_router(sounds.router)
app.include_router(payments.router)
app.include_router(subscription_changes.router)


@app.get("/")
def health_check():
    return {"status": "healthy"}
