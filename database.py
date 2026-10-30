from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from settings import settings

DATABASE_URL = settings.database_url

# Connect SQLAlchemy to the database configured in .env.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Open a separate database session for each unit of work.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    # Always close the session after the request finishes.
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
