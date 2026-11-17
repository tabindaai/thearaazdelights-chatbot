
from services.db import engine

if engine is None:
    raise RuntimeError("Database is not configured.")

with engine.connect() as connection:
    result = connection.exec_driver_sql(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )

    print("Tables in PostgreSQL:")
    for row in result:
        print(row[0])
