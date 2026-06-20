"""Versioned SQLite schema migrations."""

from __future__ import annotations

MIGRATIONS = (
    """
    CREATE TABLE subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        normalized_url TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'active', 'paused', 'deleted')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_checked_at TEXT,
        last_success_at TEXT,
        next_check_at TEXT,
        last_result_count INTEGER,
        deleted_at TEXT
    );

    CREATE INDEX idx_subscriptions_due
        ON subscriptions(status, next_check_at);

    CREATE UNIQUE INDEX idx_subscriptions_unique_live_url
        ON subscriptions(normalized_url)
        WHERE status != 'deleted';

    CREATE TABLE listings (
        listing_id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        title TEXT NOT NULL,
        price_monthly INTEGER NOT NULL CHECK (price_monthly > 0),
        location TEXT NOT NULL,
        category TEXT,
        layout TEXT,
        area_ping REAL,
        floor TEXT,
        published_text TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );

    CREATE TABLE subscription_listings (
        subscription_id INTEGER NOT NULL
            REFERENCES subscriptions(id) ON DELETE CASCADE,
        listing_id TEXT NOT NULL
            REFERENCES listings(listing_id) ON DELETE CASCADE,
        first_seen_at TEXT NOT NULL,
        notified_at TEXT,
        PRIMARY KEY (subscription_id, listing_id)
    );

    CREATE INDEX idx_subscription_listings_pending
        ON subscription_listings(subscription_id, notified_at, first_seen_at);

    CREATE TABLE notification_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subscription_id INTEGER NOT NULL,
        listing_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
        attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
        created_at TEXT NOT NULL,
        sent_at TEXT,
        error_code TEXT,
        error_message TEXT,
        FOREIGN KEY (subscription_id, listing_id)
            REFERENCES subscription_listings(subscription_id, listing_id)
            ON DELETE CASCADE
    );

    CREATE INDEX idx_notification_events_relation
        ON notification_events(subscription_id, listing_id, created_at);

    CREATE TABLE pending_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subscription_id INTEGER
            REFERENCES subscriptions(id) ON DELETE CASCADE,
        action_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'consumed', 'cancelled')),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        completed_at TEXT
    );

    CREATE INDEX idx_pending_actions_open
        ON pending_actions(status, expires_at);
    """,
    """
    CREATE TABLE bot_command_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        update_id INTEGER,
        command TEXT NOT NULL,
        authorized INTEGER NOT NULL CHECK (authorized IN (0, 1)),
        status TEXT NOT NULL CHECK (status IN ('accepted', 'rejected', 'failed')),
        subscription_id INTEGER,
        created_at TEXT NOT NULL,
        error_code TEXT,
        FOREIGN KEY (subscription_id)
            REFERENCES subscriptions(id) ON DELETE SET NULL
    );

    CREATE INDEX idx_bot_command_events_command
        ON bot_command_events(command, status, created_at);
    """,
    """
    ALTER TABLE listings
        ADD COLUMN image_url TEXT;
    """,
    """
    CREATE TABLE monitor_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        checked_count INTEGER NOT NULL CHECK (checked_count >= 0),
        succeeded_count INTEGER NOT NULL CHECK (succeeded_count >= 0),
        failed_count INTEGER NOT NULL CHECK (failed_count >= 0),
        sent_count INTEGER NOT NULL CHECK (sent_count >= 0),
        notification_failed_count INTEGER NOT NULL CHECK (notification_failed_count >= 0),
        status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
        error_code TEXT,
        error_message TEXT
    );

    CREATE INDEX idx_monitor_runs_started_at
        ON monitor_runs(started_at);

    CREATE INDEX idx_monitor_runs_status
        ON monitor_runs(status, completed_at);
    """,
)

LATEST_SCHEMA_VERSION = len(MIGRATIONS)
