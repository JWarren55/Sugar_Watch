from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)

from database import Base


# Store the Google account linked to each user's data.
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=True)
    picture = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    active = Column(Boolean, default=True, nullable=False)


# Store the user's profile and preferred display units.
class HealthProfile(Base):
    __tablename__ = "health_profile"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    height = Column(Float, nullable=False)
    sex = Column(String(6), nullable=False)
    date_of_birth = Column(Date, nullable=False)
    preferred_units = Column(String(10), default="imperial", nullable=False)
    active = Column(Boolean, default=True, nullable=False)


# Store weight and waist measurements over time.
class HealthHistory(Base):
    __tablename__ = "health_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    weight = Column(Float, nullable=True)
    waist = Column(Float, nullable=True)
    active = Column(Boolean, default=True, nullable=False)


# Record the amount of a saved food eaten at a given time.
class FoodEntry(Base):
    __tablename__ = "food_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    food_item_id = Column(
        Integer, ForeignKey("food_items.id"), nullable=True, index=True
    )
    timestamp = Column(DateTime, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    unit = Column(String(50), nullable=False)
    active = Column(Boolean, default=True, nullable=False)


# Store exercise duration, intensity, and optional measurements.
class ExerciseEntry(Base):
    __tablename__ = "exercise_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    length_minutes = Column(Float, nullable=False)
    exercise_type = Column(String(50), nullable=False)
    intensity = Column(String(50), nullable=False)
    average_heart_rate = Column(Integer, nullable=True)
    peak_heart_rate = Column(Integer, nullable=True)
    distance = Column(Float, nullable=True)
    active = Column(Boolean, default=True, nullable=False)


# Record a medication and its optional dose.
class MedicationEntry(Base):
    __tablename__ = "medication_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    medication_name = Column(String(255), nullable=False)
    dose = Column(Float, nullable=True)
    unit = Column(String(50), nullable=True)
    active = Column(Boolean, default=True, nullable=False)


# Track feeling, hunger, and headache measurements.
class MoodEntry(Base):
    __tablename__ = "mood_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    feeling = Column(String(30), nullable=True)
    hunger = Column(String(30), nullable=True)
    head = Column(String(30), nullable=True)
    active = Column(Boolean, default=True, nullable=False)


# Store manual or imported blood glucose readings.
class GlucoseReading(Base):
    __tablename__ = "glucose_readings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    glucose = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    source = Column(String(50), nullable=True)
    active = Column(Boolean, default=True, nullable=False)


# Store nutrition values for one serving of a saved food.
class FoodItem(Base):
    __tablename__ = "food_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    brand = Column(String(200), nullable=True)
    serving_size = Column(Float, nullable=True)
    serving_unit = Column(String(50), nullable=True)
    calories = Column(Float, nullable=True)
    fat = Column(Float, nullable=True)
    saturated_fat = Column(Float, nullable=True)
    trans_fat = Column(Float, nullable=True)
    cholesterol = Column(Float, nullable=True)
    sodium = Column(Float, nullable=True)
    carbs = Column(Float, nullable=True)
    fiber = Column(Float, nullable=True)
    sugar = Column(Float, nullable=True)
    added_sugar = Column(Float, nullable=True)
    protein = Column(Float, nullable=True)
    vitamin_d = Column(Float, nullable=True)
    calcium = Column(Float, nullable=True)
    iron = Column(Float, nullable=True)
    potassium = Column(Float, nullable=True)
    caffeine = Column(Float, nullable=True)
    source = Column(String(50), default="manual", nullable=False)
    external_id = Column(String(100), nullable=True)
    barcode = Column(String(50), nullable=True, index=True)
    active = Column(Boolean, default=True, nullable=False)


# Keep track of each user's favorite saved foods.
class FavoriteFood(Base):
    __tablename__ = "favorite_foods"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    food_item_id = Column(
        Integer, ForeignKey("food_items.id"), nullable=False, index=True
    )
    active = Column(Boolean, default=True, nullable=False)
