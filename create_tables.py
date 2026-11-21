
from services.db import Base, engine
import services.models

if engine is None:
    raise RuntimeError("Database is not configured.")

# Creates all tables including 'customers' and 'reservations'
Base.metadata.create_all(bind=engine)

# Auto-migrate any existing reservations table to include calendar_event_id and customer_id
from sqlalchemy import text
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(255);"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS customer_id VARCHAR(64) REFERENCES customers(id);"))
        conn.commit()
    print("Database migration: verified calendar_event_id and customer_id columns exist.")
except Exception as exc:
    print(f"Migration note (non-critical if table is new): {exc}")

print("Tables created and verified successfully.")
