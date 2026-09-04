import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.gift_catalog import gift_catalog_scheduler
from app.live_runtime import command_listener, owner_heartbeat
from app.rate_limit import RedisRateLimitMiddleware
from app.redis_store import close_redis, ping_redis
from app.routers import auth, gifts, live, payments, payment_receipts, payment_reconciliation, prefrences, subscription_changes, voice, wstts, sounds
from app.routers import paystack_webhook
import app.models


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ping_redis()
    gift_sync_task = asyncio.create_task(gift_catalog_scheduler())
    runtime_stop = asyncio.Event()
    command_task = asyncio.create_task(command_listener(runtime_stop))
    heartbeat_task = asyncio.create_task(owner_heartbeat(runtime_stop))
    try:
        yield
    finally:
        runtime_stop.set()
        for task in (command_task, heartbeat_task, gift_sync_task):
            task.cancel()
        await asyncio.gather(command_task, heartbeat_task, gift_sync_task, return_exceptions=True)
        await close_redis()


app = FastAPI(title="EchoStream Backend API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://172.20.10.6:3000"
        # your production frontend URL goes here
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"] ,
)

app.add_middleware(RedisRateLimitMiddleware)

app.include_router(auth.router)
app.include_router(voice.router)
app.include_router(wstts.router)
app.include_router(live.router)
app.include_router(prefrences.router)
app.include_router(gifts.router)
app.include_router(sounds.router)
# Register reconciliation routes first so callback/verify use Paystack subscription
# reconciliation instead of relying on the webhook payload's subscription_code.
app.include_router(payment_reconciliation.router)
# Register the dedicated Paystack webhook before payments.router. Both expose
# /payments/webhook, and FastAPI resolves the first matching route.
app.include_router(paystack_webhook.router)
app.include_router(payments.router)
app.include_router(payment_receipts.router)
app.include_router(subscription_changes.router)


@app.get("/")
def health_check():
    return {"status": "healthy"}
