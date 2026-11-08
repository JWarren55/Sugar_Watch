"""Apply storage migrations using the configured database."""

from app.db.migrations import apply_storage_migrations
from app.db.session import engine

count = apply_storage_migrations(engine)
print(f"Storage migrations complete; converted {count} legacy height values.")
