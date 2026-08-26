-- EchoStream: Fish Audio preferences / voice cloning migration.
-- Safe to run against an existing PostgreSQL database.

CREATE TABLE IF NOT EXISTS user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    tiktok_username VARCHAR,
    comment_prefix VARCHAR NOT NULL DEFAULT '',
    comment_suffix VARCHAR NOT NULL DEFAULT '',
    tts_provider VARCHAR NOT NULL DEFAULT 'edge',
    voice VARCHAR NOT NULL DEFAULT 'en-US-GuyNeural',
    fish_voice_id VARCHAR,
    pitch VARCHAR NOT NULL DEFAULT '+0Hz'
);

ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS tts_provider VARCHAR NOT NULL DEFAULT 'edge';
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS fish_voice_id VARCHAR;

UPDATE user_preferences
SET tts_provider = 'edge'
WHERE tts_provider IS NULL OR tts_provider = '';
