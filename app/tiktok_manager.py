import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict
from sqlalchemy import select
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent, FollowEvent, GiftEvent, LikeEvent
from app.database import AsyncSessionLocal
from app.live_runtime import mark_live_failed, mark_live_ready
from app.models import DBGiftPreference, DBMutedUser, DBUser, DBUserPreferences

active_sessions: Dict[int, asyncio.Queue] = {}
active_tiktok_clients: Dict[int, TikTokLiveClient] = {}
_request_times = defaultdict(deque); _last_request_at = {}; _repeat_violations = defaultdict(int)
_warmup_tasks = {}; _intentional_stops = set(); _join_boundaries = {}
_PROFANITY = {"fuck","fucking","shit","bitch","asshole","motherfucker"}; _INITIAL_SYNC_SECONDS = 2.0

async def _load_user_and_preferences(user_id):
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(DBUser).where(DBUser.id == user_id))).scalar_one_or_none()
        prefs = (await db.execute(select(DBUserPreferences).where(DBUserPreferences.user_id == user_id))).scalar_one_or_none()
        return user, prefs

def _apply_template(template, username, comment="", gift="", count=1, event_type=""):
    return (template or "").replace("{{user}}", username).replace("{{username}}", username).replace("{{comment}}", comment).replace("{{gift}}", gift).replace("{{count}}", str(count)).replace("{{event}}", event_type)
def _normalise_words(value):
    try: value = json.loads(value) if isinstance(value, str) else value
    except Exception: pass
    return [str(x).strip().lower() for x in (value or []) if str(x).strip()]
def _contains_blocked_word(text, words): return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text.lower()) for word in words)
def _contains_repeated_words(text, minimum=3):
    words=re.findall(r"[\w']+", text.lower()); run=1
    for a,b in zip(words,words[1:]):
        run=run+1 if a==b else 1
        if run>=minimum:return True
    return False
def _user_role(event):
    u=event.user
    if bool(getattr(u,"is_moderator",False) or getattr(u,"is_mod",False)):return "moderators"
    if bool(getattr(u,"is_subscriber",False) or getattr(u,"is_sub",False)):return "subscribers"
    if bool(getattr(u,"is_follower",False) or getattr(u,"is_following",False)):return "followers"
    return "all"
def _allowed_user(event,prefs):
    configured=set(_normalise_words(prefs.allowed_user_types)); return not configured or "all" in configured or _user_role(event) in configured
async def _muted(owner_id, tid, username):
    async with AsyncSessionLocal() as db:
        q=select(DBMutedUser).where(DBMutedUser.owner_id==owner_id)
        if tid and (await db.execute(q.where(DBMutedUser.tiktok_user_id==tid))).scalar_one_or_none() is not None:return True
        return (await db.execute(q.where(DBMutedUser.tiktok_username.ilike(username)))).scalar_one_or_none() is not None
async def _auto_mute(owner_id,tid,username):
    async with AsyncSessionLocal() as db:
        q=select(DBMutedUser).where(DBMutedUser.owner_id==owner_id)
        existing=(await db.execute(q.where(DBMutedUser.tiktok_user_id==tid))) if tid else (await db.execute(q.where(DBMutedUser.tiktok_username.ilike(username))))
        if existing.scalar_one_or_none() is None:
            db.add(DBMutedUser(owner_id=owner_id,tiktok_user_id=tid,tiktok_username=username,reason="spam",created_at=datetime.now(timezone.utc).replace(tzinfo=None))); await db.commit()
def _spam_blocked(user_id,username,prefs):
    if not prefs.spam_protection_enabled:return False,False
    key=(user_id,username.lower()); now=time.monotonic(); cooldown=max(0,prefs.spam_cooldown_seconds)
    if cooldown and now-_last_request_at.get(key,0)<cooldown:_repeat_violations[key]+=1; return True,bool(prefs.auto_mute_repeat_offenders and _repeat_violations[key]>=3)
    stamps=_request_times[key]
    while stamps and now-stamps[0]>=60:stamps.popleft()
    if len(stamps)>=max(1,prefs.spam_max_requests_per_minute):_repeat_violations[key]+=1; return True,bool(prefs.auto_mute_repeat_offenders and _repeat_violations[key]>=3)
    stamps.append(now); _last_request_at[key]=now; return False,False
async def _gift_override(user_id,gift_id):
    async with AsyncSessionLocal() as db:return (await db.execute(select(DBGiftPreference).where(DBGiftPreference.owner_id==user_id,DBGiftPreference.gift_id==gift_id))).scalar_one_or_none()
def _event_alert_config(prefs,event_type):
    try:
        data=json.loads(prefs.event_alerts or "{}")
        value=data.get(event_type)
        return value if isinstance(value,dict) else None
    except (TypeError,json.JSONDecodeError):return None
async def _enqueue_event(queue,prefs,msg_id,event_type,username,gift="",count=1,override=None):
    config=override or _event_alert_config(prefs,event_type)
    if not config or not config.get("enabled",True):return
    alert_type=config.get("alert_type","tts"); provider=config.get("tts_provider") or prefs.tts_provider or "edge"; voice=config.get("voice") or prefs.voice
    fish_voice_id=config.get("fish_voice_id") or prefs.fish_voice_id; fish_model=config.get("fish_model") or prefs.fish_model; pitch=config.get("pitch") or prefs.pitch
    volume=config.get("volume") if config.get("volume") is not None else prefs.volume; speed=config.get("speed") if config.get("speed") is not None else prefs.speed
    item={"id":msg_id,"event_type":event_type,"alert_type":alert_type,"text":"","provider":provider,"voice":voice,"fish_voice_id":fish_voice_id,"fish_model":fish_model,"pitch":pitch,"speed":max(.1,min(4.,float(speed)/100)),"volume":volume,"system_sound_id":config.get("system_sound_id"),"custom_audio_url":config.get("custom_audio_url"),"username":username,"gift":gift,"count":count}
    if alert_type=="tts":
        template=config.get("tts_template") or ("{{user}} sent {{gift}}" if event_type=="gift" else f"{{{{user}}}} {event_type}")
        item["text"]=_apply_template(template,username,gift=gift,count=count,event_type=event_type)
        if not item["text"].strip():return
    elif alert_type=="system_sound":
        if not item["system_sound_id"]:return
    elif alert_type=="custom_audio":
        if not item["custom_audio_url"]:return
    else:return
    print(f"[event][{event_type}] alert={alert_type} user={username} count={count}")
    if item["text"]:
        print("tstssss:::  ", item["text"])
    await queue.put(item)

def _event_time(event):
    common=getattr(event,"common",None); raw=getattr(common,"create_time",None) or getattr(common,"create_time_ms",None)
    try:
        value=float(raw)
        return value/1000 if value>100_000_000_000 else value
    except (TypeError,ValueError):return None
def _is_after_join_boundary(user_id,event):
    boundary=_join_boundaries.get(user_id)
    if boundary is None:return False
    value=_event_time(event); return value is None or value>=boundary

async def start_tiktok_session(user_id,tiktok_username):
    if user_id in active_tiktok_clients:return
    user,_=await _load_user_and_preferences(user_id)
    if user is None:mark_live_failed(user_id,active_sessions,"user not found");return
    _intentional_stops.discard(user_id); _join_boundaries.pop(user_id,None); client=TikTokLiveClient(unique_id=tiktok_username); client.logger.setLevel(logging.ERROR)
    @client.on(ConnectEvent)
    async def on_connect(event):
        _join_boundaries[user_id]=time.time()
        async def finish():
            try:
                await asyncio.sleep(_INITIAL_SYNC_SECONDS)
                if active_tiktok_clients.get(user_id) is client:mark_live_ready(user_id,active_sessions)
            except asyncio.CancelledError:return
        old=_warmup_tasks.pop(user_id,None)
        if old:old.cancel()
        _warmup_tasks[user_id]=asyncio.create_task(finish()); print(f"[live] connected user_id={user_id}")
    @client.on(CommentEvent)
    async def on_comment(event):
        print("recv: coment")
        queue=active_sessions.get(user_id)
        if queue is None or not getattr(queue,"ready",False) or not _is_after_join_boundary(user_id,event):return
        _,prefs=await _load_user_and_preferences(user_id)
        if prefs is None or not prefs.comment_speech_enabled:return
        username=(getattr(event.user,"nickname",None) or getattr(event.user,"unique_id",None) or "someone") if event.user else "someone"; tid=str(getattr(event.user,"user_id",None) or "") or None; comment=(getattr(event,"comment","") or "").strip()
        if not comment or await _muted(user_id,tid,username) or not _allowed_user(event,prefs):return
        print("comments", comment)
        if prefs.require_command_prefix:
            if not comment.startswith("!"):return
            comment=comment[1:].lstrip()
        if len(comment)>max(1,prefs.max_message_length):return
        if prefs.filter_profanity and (_contains_blocked_word(comment,list(_PROFANITY)) or _contains_blocked_word(comment,_normalise_words(prefs.blocked_words))):return
        blocked,mute=_spam_blocked(user_id,username,prefs)
        if blocked:
            if mute:await _auto_mute(user_id,tid,username)
            return
        await queue.put({"id":f"comment-{time.time_ns()}","event_type":"comment","alert_type":"tts","text":_apply_template(prefs.comment_speech_template,username,comment=comment),"provider":prefs.tts_provider,"voice":prefs.voice,"fish_voice_id":prefs.fish_voice_id,"fish_model":prefs.fish_model,"pitch":prefs.pitch,"speed":float(prefs.speed)/100,"volume":prefs.volume,"username":username})
    @client.on(FollowEvent)
    async def on_follow(event):
        queue=active_sessions.get(user_id)
        if queue is None or not getattr(queue,"ready",False) or not _is_after_join_boundary(user_id,event):return
        _,prefs=await _load_user_and_preferences(user_id)
        if prefs is None:return
        username=(getattr(event.user,"nickname",None) or getattr(event.user,"unique_id",None) or "someone") if event.user else "someone"
        await _enqueue_event(queue,prefs,f"follow-{time.time_ns()}","follow",username)
    @client.on(LikeEvent)
    async def on_like(event):
        queue=active_sessions.get(user_id)
        if queue is None or not getattr(queue,"ready",False) or not _is_after_join_boundary(user_id,event):return
        _,prefs=await _load_user_and_preferences(user_id)
        if prefs is None:return
        username=(getattr(event.user,"nickname",None) or getattr(event.user,"unique_id",None) or "someone") if event.user else "someone"; count=int(getattr(event,"count",None) or getattr(event,"like_count",None) or 1)
        await _enqueue_event(queue,prefs,f"like-{time.time_ns()}","like",username,count=count)
    @client.on(GiftEvent)
    async def on_gift(event):
        queue=active_sessions.get(user_id)
        if queue is None:
            print("[gift] dropped: no active websocket queue"); return
        if not getattr(queue,"ready",False):
            print("[gift] dropped: websocket not ready"); return
        if not _is_after_join_boundary(user_id,event):
            print("[gift] dropped: pre-join event"); return
        gift=getattr(event,"gift",None)
        streakable=bool(getattr(gift,"streakable",False)) if gift is not None else False
        repeat_end=bool(getattr(event,"repeat_end",False) or getattr(event,"streak_end",False))
        if streakable and not repeat_end:
            print("[gift] waiting for streak completion"); return
        _,prefs=await _load_user_and_preferences(user_id)
        if prefs is None:return
        username=(getattr(event.user,"nickname",None) or getattr(event.user,"unique_id",None) or "someone") if event.user else "someone"
        gift_id=str(getattr(gift,"id",None) or getattr(gift,"gift_id",None) or getattr(event,"gift_id",None) or "")
        gift_name=str(getattr(gift,"name",None) or getattr(gift,"gift_name",None) or getattr(event,"gift_name",None) or "gift")
        count=int(getattr(event,"repeat_count",None) or getattr(event,"count",None) or 1)
        print(f"[gift] received id={gift_id or 'unknown'} name={gift_name} streakable={streakable} count={count}")
        override=await _gift_override(user_id,gift_id) if gift_id else None
        override_data=None
        if override is not None:
            if not override.enabled:return
            override_data={"enabled":True,"alert_type":override.alert_type,"tts_template":override.tts_template,"tts_provider":override.tts_provider,"voice":override.voice,"fish_voice_id":override.fish_voice_id,"fish_model":override.fish_model,"system_sound_id":override.system_sound_id,"custom_audio_url":override.custom_audio_url,"volume":override.volume,"speed":override.speed,"pitch":override.pitch}
        await _enqueue_event(queue,prefs,f"gift-{time.time_ns()}","gift",username,gift=gift_name,count=count,override=override_data)
    @client.on(DisconnectEvent)
    async def on_disconnect(event):
        active_tiktok_clients.pop(user_id,None); _join_boundaries.pop(user_id,None)
        if user_id in _intentional_stops:_intentional_stops.discard(user_id);return
        mark_live_failed(user_id,active_sessions,"TikTok disconnected")
    async def run():
        try:
            print(f"[live] connecting user_id={user_id} username=@{tiktok_username}"); await client.start(fetch_gift_info=True)
        except Exception as exc:
            active_tiktok_clients.pop(user_id,None); _join_boundaries.pop(user_id,None); mark_live_failed(user_id,active_sessions,str(exc))
    active_tiktok_clients[user_id]=client; asyncio.create_task(run())

async def stop_tiktok_session(user_id):
    _intentional_stops.add(user_id); task=_warmup_tasks.pop(user_id,None)
    if task:task.cancel()
    _join_boundaries.pop(user_id,None); client=active_tiktok_clients.pop(user_id,None)
    if client is not None:await client.disconnect()
    for key in [k for k in _request_times if k[0]==user_id]:_request_times.pop(key,None);_last_request_at.pop(key,None);_repeat_violations.pop(key,None)
