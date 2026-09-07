from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Float, Date
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
    
class HealthProfile(Base):
    __tablename__ = 'health_profile'
    
    id = Column(
        Integer,
        primary_key=True,
        index=True
    )
    
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    
    height = Column(
        Float,
        nullable=False
    )
    
    sex = Column(
        String(6),
        nullable=False
    )
    
    date_of_birth = Column(
        Date,
        nullable=False
    )
    
    preferred_units = Column(
        String(10),
        default="imperial",
        nullable=False
    )
    
    active = Column(
        Boolean,
        default=True,
        nullable=False
    )
    
class HealthHistory(Base):
    __tablename__ = 'health_history'
    
    id = Column(
        Integer,
        primary_key=True,
        index=True
    )
        
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    
    timestamp = Column(
        DateTime,
        nullable=False,
        index=True
    )
    
    weight = Column(
        Float,
        nullable=True
    )
    
    waist = Column(
        Float,
        nullable=True
    )
    
    active = Column(
        Boolean,
        default=True,
        nullable=False
    )
    
class FoodEntries(Base):
    __tablename__ = "food_entries"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    timestamp = Column(
        DateTime,
        nullable=False,
        index=True
    )
    
    name = Column(
        String(200),
        nullable=False
    )

    calories = Column(
        Float,
        nullable=True
    )

    fat = Column(
        Float,
        nullable=True
    )

    saturated_fat = Column(
        Float,
        nullable=True
    )

    trans_fat = Column(
        Float,
        nullable=True
    )

    cholesterol = Column(
        Float,
        nullable=True
    )

    sodium = Column(
        Float,
        nullable=True
    )

    carbs = Column(
        Float,
        nullable=True
    )

    fiber = Column(
        Float,
        nullable=True
    )

    sugar = Column(
        Float,
        nullable=True
    )

    added_sugar = Column(
        Float,
        nullable=True
    )

    protein = Column(
        Float,
        nullable=True
    )

    vitamin_d = Column(
        Float,
        nullable=True
    )

    calcium = Column(
        Float,
        nullable=True
    )

    iron = Column(
        Float,
        nullable=True
    )

    potassium = Column(
        Float,
        nullable=True
    )
    
    caffeine = Column(
        Float,
        nullable=True
    )

    active = Column(
        Boolean,
        default=True,
        nullable=False
    )

class ExerciseEntry(Base):
    __tablename__ = "exercise_entries"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    timestamp = Column(
        DateTime,
        nullable=False,
        index=True
    )

    length_minutes = Column(
        Float,
        nullable=False
    )

    exercise_type = Column(
        String(50),
        nullable=False
    )

    intensity = Column(
        String(50),
        nullable=False
    )

    average_heart_rate = Column(
        Integer,
        nullable=True
    )

    peak_heart_rate = Column(
        Integer,
        nullable=True
    )

    distance = Column(
        Float,
        nullable=True
    )

    active = Column(
        Boolean,
        default=True,
        nullable=False
    )

class MedicationEntry(Base):
    __tablename__ = "medication_entries"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    timestamp = Column(
        DateTime,
        nullable=False,
        index=True
    )

    medication_name = Column(
        String(255),
        nullable=False
    )

    dose = Column(
        Float,
        nullable=True
    )

    unit = Column(
        String(50),
        nullable=True
    )

    active = Column(
        Boolean,
        default=True,
        nullable=False
    )

class moodEntries(Base):
    __tablename__ = "mood_entries"
    
    id = Column(
        Integer,
        primary_key=True,
        index=True
    )
    
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    
    timestamp = Column(
        DateTime,
        nullable=False,
        index=True
    )

    feeling = Column(
        String(30),
        nullable=True
    )
    
    hunger = Column(
        String(30),
        nullable=True
    )
    
    head = Column(
        String(30),
        nullable=True
    )
    
    active = Column(
        Boolean,
        default=True,
        nullable=False
    )
    
class GlucoseReading(Base):
    __tablename__ = "glucose_readings"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    glucose = Column(
        Integer,
        nullable=False
    )

    timestamp = Column(
        DateTime,
        nullable=False,
        index=True
    )

    source = Column(
        String(50),
        nullable=True
    )

    active = Column(
        Boolean,
        default=True,
        nullable=False
    )
    