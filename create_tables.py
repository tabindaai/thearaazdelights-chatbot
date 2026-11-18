
from services.db import Base, engine
import services.models


if engine is None:
    raise RuntimeError("Database is not configured.")

Base.metadata.create_all(bind=engine)

print("Tables created successfully (if they did not already exist).")
