from app.db import connect


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """Add a column to an existing local SQLite database (no destructive rewrite)."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS sources(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            format TEXT NOT NULL,
            fixture_path TEXT NOT NULL,
            watermark_ts TEXT,
            lookback_seconds INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS runs(
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            parsed_count INTEGER NOT NULL,
            upserted_count INTEGER NOT NULL,
            conflict_count INTEGER NOT NULL,
            skipped_count INTEGER NOT NULL,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS staging_rows(
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            business_key TEXT NOT NULL,
            event_ts TEXT NOT NULL,
            source_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            disposition TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS canonical_items(
            id INTEGER PRIMARY KEY,
            business_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            event_ts TEXT NOT NULL,
            source_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            run_id INTEGER,
            lineage_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS conflicts(
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            business_key TEXT NOT NULL,
            existing_payload TEXT NOT NULL,
            incoming_payload TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            incoming_revision INTEGER,
            incoming_event_ts TEXT,
            existing_source_id INTEGER,
            existing_revision INTEGER,
            existing_event_ts TEXT,
            existing_run_id INTEGER,
            existing_lineage_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS lineage_events(
            id INTEGER PRIMARY KEY,
            business_key TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            run_id INTEGER NOT NULL,
            source_revision INTEGER NOT NULL,
            event_ts TEXT NOT NULL,
            written_at TEXT NOT NULL,
            action TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            previous_lineage_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_lineage_events_key
            ON lineage_events(business_key, id);
        CREATE INDEX IF NOT EXISTS idx_lineage_events_run
            ON lineage_events(run_id);
        CREATE INDEX IF NOT EXISTS idx_conflicts_key
            ON conflicts(business_key, id);
        """
    )

    # Upgrade databases created before row-level lineage existed.
    _ensure_column(conn, "canonical_items", "run_id", "INTEGER")
    _ensure_column(conn, "canonical_items", "lineage_id", "INTEGER")
    for name, ddl in (
        ("incoming_revision", "INTEGER"),
        ("incoming_event_ts", "TEXT"),
        ("existing_source_id", "INTEGER"),
        ("existing_revision", "INTEGER"),
        ("existing_event_ts", "TEXT"),
        ("existing_run_id", "INTEGER"),
        ("existing_lineage_id", "INTEGER"),
    ):
        _ensure_column(conn, "conflicts", name, ddl)

    if conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"] == 0:
        conn.executemany(
            """
            INSERT INTO sources(name, format, fixture_path, watermark_ts, lookback_seconds, enabled, note)
            VALUES (?,?,?,?,?,?,?)
            """,
            [
                (
                    "Alpha Catalog",
                    "json",
                    "alpha_catalog.json",
                    None,
                    0,
                    1,
                    "clean：三件独立货号，首跑应全部 upsert",
                ),
                (
                    "Beta Offers",
                    "jsonl",
                    "beta_offers.jsonl",
                    None,
                    0,
                    1,
                    "dirty：SKU-1001 与 Alpha 同键异价→冲突；另含独立货号",
                ),
                (
                    "Gamma Shelf",
                    "xml",
                    "gamma_shelf.xml",
                    None,
                    0,
                    1,
                    "xml 源：两件独立货号",
                ),
            ],
        )
        conn.execute("INSERT INTO settings(key, value) VALUES ('project_label', 'Feedstitch')")
        conn.execute("INSERT INTO settings(key, value) VALUES ('default_mode', 'incremental')")
    conn.commit()
    conn.close()
