from typing import List

import edge_tts
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_active_subscription, require_pro_subscription
from app.fish_audio import FishAudioError, create_voice_clone, stream_tts
from app.models import DBUser, DBUserPreferences
from app.schemas import FishVoiceCloneResponse, TTSTextPayloadSchema, VoiceDetailSchema

router = APIRouter(tags=["Text-to-Speech"])
CACHED_VOICES: List[VoiceDetailSchema] = []


async def get_all_edge_voices() -> List[VoiceDetailSchema]:
    global CACHED_VOICES
    if not CACHED_VOICES:
        all_voices = await edge_tts.list_voices()
        CACHED_VOICES = [
            VoiceDetailSchema(
                name=v["Name"], short_name=v["ShortName"], gender=v["Gender"], locale=v["Locale"]
            )
            for v in all_voices
        ]
    return CACHED_VOICES


async def tts_streaming_generator(text: str, voice: str, pitch: str = "+0Hz"):
    """Stream native Edge TTS audio chunks."""
    communicate = edge_tts.Communicate(text, voice, pitch=pitch)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]


@router.get("/v1/tts/voices", response_model=List[VoiceDetailSchema])
async def list_voices(current_user: DBUser = Depends(get_current_user)):
    return await get_all_edge_voices()


@router.post("/v1/tts")
async def text_to_speech(
    payload: TTSTextPayloadSchema,
    current_user: DBUser = Depends(require_active_subscription),
    db: Session = Depends(get_db),
):
    """TTS using the provider and Fish model selected in user preferences."""
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text parameter cannot be empty.")

    prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == current_user.id).first()
    provider = (payload.provider or (prefs.tts_provider if prefs else "edge")).lower()

    if provider == "fish":
        if current_user.plan.lower() != "pro":
            raise HTTPException(status_code=403, detail="Fish Audio is available on the Pro plan.")

        model = payload.fish_model or (prefs.fish_model if prefs else settings.FISH_AUDIO_PRO_MODEL)
        if model not in {settings.FISH_AUDIO_PRO_MODEL, settings.FISH_AUDIO_FREE_MODEL}:
            raise HTTPException(status_code=400, detail="Unsupported Fish Audio model.")

        voice_id = payload.voice or (prefs.fish_voice_id if prefs else None)
        return StreamingResponse(
            stream_tts(payload.text, reference_id=voice_id, model=model, speed=payload.speed),
            media_type="audio/mpeg",
        )

    if provider != "edge":
        raise HTTPException(status_code=400, detail="Unsupported TTS provider.")

    voice = payload.voice or (prefs.voice if prefs else "en-US-GuyNeural")
    pitch = prefs.pitch if prefs else "+0Hz"
    return StreamingResponse(tts_streaming_generator(payload.text, voice, pitch), media_type="audio/mpeg")


@router.post("/v1/tts/fish/clone", response_model=FishVoiceCloneResponse)
async def clone_fish_voice(
    title: str,
    audio: UploadFile = File(...),
    current_user: DBUser = Depends(require_pro_subscription),
    db: Session = Depends(get_db),
):
    """Create a private Fish Audio voice clone and save it to user preferences."""
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Please upload an audio reference file.")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Voice title cannot be empty.")

    prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == current_user.id).first()
    if prefs is None:
        prefs = DBUserPreferences(user_id=current_user.id)
        db.add(prefs)

    try:
        voice_id = await create_voice_clone(
            title=title.strip(),
            audio=audio.file,
            filename=audio.filename or "reference_audio",
            content_type=audio.content_type,
        )
    except FishAudioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    prefs.tts_provider = "fish"
    prefs.fish_voice_id = voice_id
    prefs.voice = voice_id
    db.commit()
    db.refresh(prefs)

    return FishVoiceCloneResponse(
        voice_id=voice_id,
        message="Voice cloned successfully and selected as your Fish Audio voice.",
    )
