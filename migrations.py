"""Compatibility entry point for python -m migrations."""

from app.db.migrations import apply_storage_migrations

if __name__ == "__main__":
    from app.db.session import engine

    count = apply_storage_migrations(engine)
    print(f"Storage migrations complete; converted {count} legacy height values.")
