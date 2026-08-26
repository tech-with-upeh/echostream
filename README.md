# EchoStream

## Fish Audio Pro TTS

The `feature/fish-audio-pro` branch adds Fish Audio as a Pro-only TTS provider while keeping the existing Microsoft Edge TTS path intact.

### Environment

Add the Fish Audio API key to the backend environment. The key stays server-side and is never returned to the mobile client:

```env
FISH_AUDIO_API_KEY=your_fish_audio_api_key
FISH_AUDIO_BASE_URL=https://api.fish.audio
FISH_AUDIO_PRO_MODEL=s2-pro
FISH_AUDIO_FREE_MODEL=s2.1-pro-free
FISH_AUDIO_DEFAULT_FORMAT=mp3
FISH_AUDIO_DEFAULT_SAMPLE_RATE=44100
FISH_AUDIO_DEFAULT_BITRATE=128
```

### Preferences

Users can select `edge` or `fish` through `/v1/preferences`. Fish Audio requires the `pro` plan. Fish preferences also store the selected model (`s2-pro` or `s2.1-pro-free`) and the persistent cloned voice ID.

### Voice cloning

`POST /v1/tts/fish/clone` accepts an audio reference and creates a private Fish Audio voice model. The returned model ID is persisted in `user_preferences.fish_voice_id` and automatically selected for Fish TTS.

### Live comments

The existing `/ws/v1/tts` socket now reads the user's TTS provider, Fish model, cloned voice, and Edge pitch from preferences. Comments remain serialized so generated audio does not overlap.

### Database migration

For an existing PostgreSQL database, run:

```bash
psql "$DATABASE_URL" -f scripts/migrate_fish_audio.sql
```

The migration is intentionally separate because `Base.metadata.create_all()` does not alter an existing table.
