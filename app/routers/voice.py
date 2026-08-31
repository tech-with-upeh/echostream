from datetime import datetime, timezone
from typing import List

import edge_tts
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db, require_active_subscription, require_pro_subscription
from app.fish_audio import FishAudioError, create_voice_clone, list_public_voice_models, stream_tts
from app.models import DBFishVoice, DBUser, DBUserPreferences
from app.schemas import FishVoiceCloneResponse, FishVoiceDetailSchema, TTSTextPayloadSchema, TTSVoiceCatalogSchema, VoiceDetailSchema

router = APIRouter(tags=["Text-to-Speech"])
CACHED_VOICES: List[VoiceDetailSchema] = []


async def get_all_edge_voices() -> List[VoiceDetailSchema]:
    global CACHED_VOICES
    if not CACHED_VOICES:
        all_voices = await edge_tts.list_voices()
        CACHED_VOICES = [VoiceDetailSchema(name=v["Name"], short_name=v["ShortName"], gender=v["Gender"], locale=v["Locale"]) for v in all_voices]
    return CACHED_VOICES


async def tts_streaming_generator(text: str, voice: str, pitch: str = "+0Hz"):
    communicate = edge_tts.Communicate(text, voice, pitch=pitch)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]


def _fish_voice_response(model: dict) -> FishVoiceDetailSchema:
    return FishVoiceDetailSchema(id=model["_id"], name=model.get("title") or "Untitled Fish voice", voice_type=("cloned" if model.get("visibility") == "private" else "library"), description=model.get("description") or "", languages=model.get("languages") or [], visibility=model.get("visibility") or "public")


def _saved_fish_voice_response(voice: DBFishVoice) -> FishVoiceDetailSchema:
    return FishVoiceDetailSchema(id=voice.voice_id, name=voice.title, voice_type="cloned", description=voice.description or "", languages=[], visibility="private")


@router.get("/v1/tts/voices", response_model=TTSVoiceCatalogSchema)
async def list_voices(current_user: DBUser = Depends(get_current_user)):
    edge_voices = await get_all_edge_voices()
    if current_user.plan.lower() != "pro": return TTSVoiceCatalogSchema(edge=edge_voices, fish=[])
    try: fish_models = await list_public_voice_models()
    except FishAudioError as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc
    fish_voices = [_fish_voice_response(model) for model in fish_models if model.get("state") in {None, "created", "trained"}]
    return TTSVoiceCatalogSchema(edge=edge_voices, fish=fish_voices)


@router.get("/v1/tts/fish/voices", response_model=list[FishVoiceDetailSchema])
async def list_fish_cloned_voices(current_user: DBUser = Depends(require_pro_subscription), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBFishVoice).where(DBFishVoice.user_id == current_user.id).order_by(DBFishVoice.created_at.desc()))
    return [_saved_fish_voice_response(voice) for voice in result.scalars().all()]


@router.post("/v1/tts")
async def text_to_speech(payload: TTSTextPayloadSchema, current_user: DBUser = Depends(require_active_subscription), db: AsyncSession = Depends(get_db)):
    if not payload.text.strip(): raise HTTPException(status_code=400, detail="Text parameter cannot be empty.")
    result = await db.execute(select(DBUserPreferences).where(DBUserPreferences.user_id == current_user.id)); prefs = result.scalar_one_or_none()
    provider = (payload.provider or (prefs.tts_provider if prefs else "edge")).lower()
    if provider == "fish":
        if current_user.plan.lower() != "pro": raise HTTPException(status_code=403, detail="Fish Audio is available on the Pro plan.")
        model = payload.fish_model or (prefs.fish_model if prefs else settings.FISH_AUDIO_PRO_MODEL)
        if model not in {settings.FISH_AUDIO_PRO_MODEL, settings.FISH_AUDIO_FREE_MODEL}: raise HTTPException(status_code=400, detail="Unsupported Fish Audio model.")
        voice_id = payload.voice or (prefs.fish_voice_id if prefs else None)
        return StreamingResponse(stream_tts(payload.text, reference_id=voice_id, model=model, speed=payload.speed), media_type="audio/mpeg")
    if provider != "edge": raise HTTPException(status_code=400, detail="Unsupported TTS provider.")
    voice = payload.voice or (prefs.voice if prefs else "en-US-GuyNeural"); pitch = prefs.pitch if prefs else "+0Hz"
    return StreamingResponse(tts_streaming_generator(payload.text, voice, pitch), media_type="audio/mpeg")


@router.post("/v1/tts/fish/clone", response_model=FishVoiceCloneResponse)
async def clone_fish_voice(title: str = Form(...), description: str = Form(""), tags: str = Form(""), reference_text: str | None = Form(None), enhance_audio_quality: bool = Form(True), generate_sample: bool = Form(False), audio: list[UploadFile] = File(...), current_user: DBUser = Depends(require_pro_subscription), db: AsyncSession = Depends(get_db)):
    if not title.strip(): raise HTTPException(status_code=400, detail="Voice title cannot be empty.")
    if len(audio) > 5: raise HTTPException(status_code=400, detail="You can upload at most 5 audio reference files.")
    audio_files = []
    for upload in audio:
        if not upload.content_type or not upload.content_type.startswith("audio/"): raise HTTPException(status_code=400, detail=f"{upload.filename or 'File'} is not an audio file.")
        audio_files.append((upload.filename or "reference_audio", upload.file, upload.content_type))
    result = await db.execute(select(DBUserPreferences).where(DBUserPreferences.user_id == current_user.id)); prefs = result.scalar_one_or_none()
    if prefs is None: prefs = DBUserPreferences(user_id=current_user.id); db.add(prefs)
    try:
        payload = await create_voice_clone(title=title.strip(), description=description.strip(), tags=[tag.strip() for tag in tags.split(",") if tag.strip()], reference_text=reference_text.strip() if reference_text else None, audio_files=audio_files, enhance_audio_quality=enhance_audio_quality, generate_sample=generate_sample)
    except FishAudioError as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc
    voice_id = payload.get("_id")
    db.add(DBFishVoice(user_id=current_user.id, voice_id=voice_id, title=title.strip(), description=description.strip(), model=settings.FISH_AUDIO_PRO_MODEL, created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    prefs.tts_provider = "fish"; prefs.fish_voice_id = voice_id; prefs.voice = voice_id
    await db.commit(); await db.refresh(prefs)
    return FishVoiceCloneResponse(voice_id=voice_id, message="Voice cloned successfully and selected as your Fish Audio voice.")
