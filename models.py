from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(
        Integer, 
        primary_key=True, 
        index=True
    )

    google_id = Column(
        String(255),
        unique=True,
        nullable=False
    )

    email = Column(
        String(255),
        unique=True,
        nullable=False
    )

    name = Column(
        String(255),
        nullable=True
    )

    picture = Column(
        String(1000),
        nullable=True
    )
    
    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    active = Column(
        Boolean,
        default=True,
        nullable=False
    )