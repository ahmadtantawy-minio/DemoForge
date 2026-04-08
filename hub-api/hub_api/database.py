import aiosqlite
from pathlib import Path
from .config import settings


async def init_db():
    if settings.database_path == ":memory:":
        return
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.database_path) as db:
        await _create_tables(db)


async def _create_tables(db: aiosqlite.Connection):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS field_architects (
            fa_id TEXT PRIMARY KEY,
            fa_name TEXT NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            permissions TEXT NOT NULL DEFAULT '{}',
            registered_at TEXT NOT NULL,
            last_seen_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            metadata TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fa_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            timestamp TEXT NOT NULL,
            received_at TEXT NOT NULL,
            FOREIGN KEY (fa_id) REFERENCES field_architects(fa_id)
        );
        CREATE INDEX IF NOT EXISTS idx_events_fa_id ON events(fa_id);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_fa_api_key ON field_architects(api_key);
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    await db.commit()


async def get_db():
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    try:
        await _create_tables(db)
        yield db
    finally:
        await db.close()
