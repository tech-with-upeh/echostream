-- EchoStream: registry for Fish Audio clones created for users.
-- Safe to run against an existing PostgreSQL database.

CREATE TABLE IF NOT EXISTS fish_voices (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    voice_id VARCHAR NOT NULL UNIQUE,
    title VARCHAR NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    model VARCHAR NOT NULL DEFAULT 's2-pro',
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_fish_voices_user_id ON fish_voices(user_id);
CREATE INDEX IF NOT EXISTS ix_fish_voices_voice_id ON fish_voices(voice_id);
