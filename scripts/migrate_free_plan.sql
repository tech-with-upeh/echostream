-- EchoStream billing migration
-- Starter is the permanent free plan. There is no free trial.
-- Run this once against the existing PostgreSQL database before starting the API.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS plan VARCHAR;

UPDATE users
SET plan = 'starter'
WHERE plan IS NULL;

ALTER TABLE users
    ALTER COLUMN plan SET DEFAULT 'starter';

ALTER TABLE users
    ALTER COLUMN plan SET NOT NULL;

ALTER TABLE users
    ALTER COLUMN trial_ends_at DROP NOT NULL;

UPDATE users
SET
    plan = CASE
        WHEN plan IS NULL OR plan = 'free_trial' THEN 'starter'
        ELSE plan
    END,
    subscription_status = CASE
        WHEN subscription_status = 'free_trial' OR subscription_status IS NULL THEN 'active'
        ELSE subscription_status
    END,
    trial_ends_at = NULL
WHERE subscription_status = 'free_trial'
   OR subscription_status IS NULL
   OR plan IS NULL;

-- Starter users should not have a paid subscription period.
UPDATE users
SET subscription_ends_at = NULL
WHERE plan = 'starter';
