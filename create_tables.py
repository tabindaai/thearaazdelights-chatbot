
from services.db import Base, engine
import services.models

# Note: Google OAuth tokens are stored in a separate SQLite file (oauth_tokens.db)
# managed by services/oauth_store.py. That table is auto-created on first run.
# The calendar_event_id column is part of the Reservation model and will be
# created by create_all() below if the table is new, or requires this SQL if upgrading:
# ALTER TABLE reservations ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(255);

if engine is None:
    raise RuntimeError("Database is not configured.")

Base.metadata.create_all(bind=engine)

# Auto-migrate any existing reservations table to include calendar_event_id
from sqlalchemy import text
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(255);"))
        conn.commit()
    print("Database migration: verified calendar_event_id column exists.")
except Exception as exc:
    print(f"Migration note (non-critical if table is new): {exc}")

print("Tables created and verified successfully.")
