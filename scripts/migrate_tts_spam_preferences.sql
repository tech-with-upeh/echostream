ALTER TABLE user_preferences
    ADD COLUMN IF NOT EXISTS volume INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS speed INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS emoji_to_words BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS filter_profanity BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS require_command_prefix BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS max_message_length INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS comment_speech_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS comment_speech_template VARCHAR NOT NULL DEFAULT '{{user}} said {{comment}}',
    ADD COLUMN IF NOT EXISTS event_speech_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS event_speech_template VARCHAR NOT NULL DEFAULT '{{user}} sent {{gift}}',
    ADD COLUMN IF NOT EXISTS gift_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS gift_alert_type VARCHAR NOT NULL DEFAULT 'tts',
    ADD COLUMN IF NOT EXISTS gift_tts_template VARCHAR NOT NULL DEFAULT '{{user}} sent {{gift}}',
    ADD COLUMN IF NOT EXISTS gift_tts_voice VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS gift_tts_provider VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS gift_fish_voice_id VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS gift_fish_model VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS gift_system_sound_id VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS gift_custom_audio_url VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS gift_volume INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS gift_speed INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS allowed_user_types VARCHAR NOT NULL DEFAULT '["all"]',
    ADD COLUMN IF NOT EXISTS minimum_account_age_days INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS blocked_words TEXT NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS spam_protection_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS block_repeated_words BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS auto_mute_repeat_offenders BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS spam_cooldown_seconds INTEGER NOT NULL DEFAULT 2,
    ADD COLUMN IF NOT EXISTS spam_max_requests_per_minute INTEGER NOT NULL DEFAULT 10;

UPDATE user_preferences
SET comment_speech_enabled = COALESCE(speech_prefix_enabled, FALSE),
    comment_speech_template = COALESCE(speech_prefix_template, '{{user}} said {{comment}}')
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'user_preferences' AND column_name = 'speech_prefix_enabled'
);

ALTER TABLE user_preferences
    DROP COLUMN IF EXISTS comment_prefix,
    DROP COLUMN IF EXISTS comment_suffix,
    DROP COLUMN IF EXISTS speech_prefix_enabled,
    DROP COLUMN IF EXISTS speech_prefix_template;

CREATE TABLE IF NOT EXISTS muted_users (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tiktok_user_id VARCHAR NULL,
    tiktok_username VARCHAR NOT NULL,
    reason VARCHAR NOT NULL DEFAULT 'manual',
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_muted_users_owner_id ON muted_users(owner_id);
CREATE INDEX IF NOT EXISTS ix_muted_users_tiktok_user_id ON muted_users(tiktok_user_id);

CREATE TABLE IF NOT EXISTS gift_preferences (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gift_id VARCHAR NOT NULL,
    gift_name VARCHAR NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    alert_type VARCHAR NOT NULL DEFAULT 'tts',
    tts_template VARCHAR NULL,
    tts_provider VARCHAR NULL,
    voice VARCHAR NULL,
    fish_voice_id VARCHAR NULL,
    fish_model VARCHAR NULL,
    system_sound_id VARCHAR NULL,
    custom_audio_url VARCHAR NULL,
    volume INTEGER NULL,
    speed INTEGER NULL,
    pitch VARCHAR NULL
);

CREATE INDEX IF NOT EXISTS ix_gift_preferences_owner_id ON gift_preferences(owner_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_gift_preferences_owner_gift ON gift_preferences(owner_id, gift_id);
