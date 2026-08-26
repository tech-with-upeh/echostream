from typing import List

import edge_tts
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db, require_active_subscription, require_pro_subscription
from app.fish_audio import FishAudioError, create_voice_clone, list_owned_voice_models, list_voice_models, stream_tts
from app.models import DBFishVoice, DBUser, DBUserPreferences
from app.schemas import (
    FishVoiceCloneResponse,
    FishVoiceDetailSchema,
    TTSTextPayloadSchema,
    TTSVoiceCatalogSchema,
    VoiceDetailSchema,
)

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


def _fish_voice_response(model: dict) -> FishVoiceDetailSchema:
    return FishVoiceDetailSchema(
        id=model["_id"],
        name=model.get("title") or "Untitled Fish voice",
        voice_type=("cloned" if model.get("visibility") == "private" else "library"),
        description=model.get("description") or "",
        languages=model.get("languages") or [],
        visibility=model.get("visibility") or "public",
    )


@router.get("/v1/tts/voices", response_model=TTSVoiceCatalogSchema)
async def list_voices(current_user: DBUser = Depends(get_current_user)):
    """Return the public voice catalog available to the current user."""
    edge_voices = await get_all_edge_voices()

    if current_user.plan.lower() != "pro":
        return TTSVoiceCatalogSchema(edge=edge_voices, fish=[])

    try:
        fish_models = await list_voice_models()
    except FishAudioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    fish_voices = [_fish_voice_response(model) for model in fish_models if model.get("state") in {None, "created", "trained"}]
    return TTSVoiceCatalogSchema(edge=edge_voices, fish=fish_voices)


@router.get("/v1/tts/fish/voices", response_model=list[FishVoiceDetailSchema])
async def list_fish_cloned_voices(current_user: DBUser = Depends(require_pro_subscription)):
    """Return only Fish Audio voices owned by the EchoStream Fish workspace."""
    try:
        fish_models = await list_owned_voice_models()
    except FishAudioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return [
        _fish_voice_response(model)
        for model in fish_models
        if model.get("visibility") == "private"
        and model.get("state") in {None, "created", "trained"}
    ]


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
