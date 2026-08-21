import edge_tts
from fastapi import APIRouter, Depends
from typing import List

from app.dependencies import get_current_user, require_active_subscription
from app.models import DBUser
from app.schemas import TTSTextPayloadSchema, VoiceDetailSchema

router = APIRouter(tags=["Text-to-Speech"])

# In-memory global cache to store voices so we only fetch them from Microsoft once
CACHED_VOICES: List[VoiceDetailSchema] = []

async def get_all_edge_voices() -> List[VoiceDetailSchema]:
    """Helper function to fetch and format voices from edge-tts."""
    global CACHED_VOICES
    if not CACHED_VOICES:
        all_voices = await edge_tts.list_voices()
        CACHED_VOICES = [
            VoiceDetailSchema(
                name=v["Name"],
                short_name=v["ShortName"],
                gender=v["Gender"],
                locale=v["Locale"]
            )
            for v in all_voices
        ]
    return CACHED_VOICES


async def tts_streaming_generator(text: str, voice: str):
    """Asynchronously streams native binary audio chunks from edge-tts."""
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]


@router.get("/v1/tts/voices", response_model=List[VoiceDetailSchema])
async def list_voices(current_user: DBUser = Depends(get_current_user)):
    """
    Protected endpoint to list all available Microsoft Edge TTS voice models.
    Requires a valid login token, but works even if the free trial has expired.
    """
    voices = await get_all_edge_voices()
    return voices


@router.post("/v1/tts")
async def text_to_speech(
    payload: TTSTextPayloadSchema,
    current_user: DBUser = Depends(require_active_subscription)
):
    """
    Protected endpoint to convert text to speech. 
    Requires an active free trial or paid premium subscription.
    """
    from fastapi.responses import StreamingResponse
    if not payload.text.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Text parameter cannot be empty.")
    
    return StreamingResponse(
        tts_streaming_generator(payload.text, payload.voice),
        media_type="audio/mpeg"
    )

