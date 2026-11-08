from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime

from app.db.session import Base

HEALTH_TIMESTAMP = DateTime().with_variant(MySQLDateTime(fsp=6), "mysql")


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
    __table_args__ = (
        Index("uq_active_health_profile", "active_profile_user_id", unique=True),
    )
    active_profile_user_id = Column(
        Integer, Computed("CASE WHEN active = 1 THEN user_id ELSE NULL END")
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Store height in inches, regardless of the display preference.
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
    deleted_at = Column(DateTime, nullable=True)


# Record the amount of a saved food eaten at a given time.
class FoodEntry(Base):
    __tablename__ = "food_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    food_item_id = Column(
        Integer, ForeignKey("food_items.id"), nullable=True, index=True
    )
    # Store the food name, serving basis, and nutrition totals at log time.
    nutrition_snapshot = Column(JSON, nullable=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    unit = Column(String(50), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


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
    deleted_at = Column(DateTime, nullable=True)


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
    deleted_at = Column(DateTime, nullable=True)


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
    deleted_at = Column(DateTime, nullable=True)


# Store manual or imported blood glucose readings.
class GlucoseReading(Base):
    __tablename__ = "glucose_readings"
    __table_args__ = (
        Index("uq_user_glucose_import", "user_id", "import_key", unique=True),
    )
    import_key = Column(String(64), nullable=True)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    glucose = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    source = Column(String(50), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


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
    deleted_at = Column(DateTime, nullable=True)


# Keep track of each user's favorite saved foods.
class FavoriteFood(Base):
    __tablename__ = "favorite_foods"
    __table_args__ = (
        Index("uq_user_favorite", "user_id", "food_item_id", unique=True),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    food_item_id = Column(
        Integer, ForeignKey("food_items.id"), nullable=False, index=True
    )
    active = Column(Boolean, default=True, nullable=False)


class SleepInterval(Base):
    """A source sleep interval, not a pre-summed night's duration."""

    __tablename__ = "sleep_intervals"
    __table_args__ = (
        Index("uq_user_sleep_import", "user_id", "import_key", unique=True),
        Index("ix_sleep_user_active_start", "user_id", "active", "start_time"),
        CheckConstraint("end_time > start_time", name="ck_sleep_positive_interval"),
        CheckConstraint(
            "stage IN ('in_bed','awake','asleep','core','deep','rem')",
            name="ck_sleep_stage",
        ),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_time = Column(HEALTH_TIMESTAMP, nullable=False)
    end_time = Column(HEALTH_TIMESTAMP, nullable=False)
    stage = Column(String(20), nullable=False)
    source = Column(String(50), default="apple_health", nullable=False)
    source_name = Column(String(255), nullable=True)
    external_id = Column(String(255), nullable=True)
    import_key = Column(String(64), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class HealthMetricSample(Base):
    """Timestamped activity and vital samples with explicit canonical units."""

    __tablename__ = "health_metric_samples"
    __table_args__ = (
        Index("uq_user_health_metric_import", "user_id", "import_key", unique=True),
        Index("ix_health_metric_user_kind_start", "user_id", "metric", "start_time"),
        CheckConstraint("end_time >= start_time", name="ck_health_metric_interval"),
        CheckConstraint("value >= 0", name="ck_health_metric_nonnegative"),
        CheckConstraint(
            "(metric = 'steps' AND unit = 'count') OR "
            "(metric = 'active_energy' AND unit = 'kcal') OR "
            "(metric = 'body_weight' AND unit = 'lb') OR "
            "(metric IN ('heart_rate','resting_heart_rate') AND unit = 'bpm') OR "
            "(metric = 'heart_rate_variability' AND unit = 'ms')",
            name="ck_health_metric_unit",
        ),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_time = Column(HEALTH_TIMESTAMP, nullable=False)
    end_time = Column(HEALTH_TIMESTAMP, nullable=False)
    metric = Column(String(40), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(10), nullable=False)
    source = Column(String(50), default="apple_health", nullable=False)
    source_name = Column(String(255), nullable=True)
    external_id = Column(String(255), nullable=True)
    import_key = Column(String(64), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class HealthWorkout(Base):
    """Keep imported workouts separate from manually recorded exercise."""

    __tablename__ = "health_workouts"
    __table_args__ = (
        Index("uq_user_health_workout_import", "user_id", "import_key", unique=True),
        Index("ix_health_workout_user_active_start", "user_id", "active", "start_time"),
        CheckConstraint("end_time > start_time", name="ck_health_workout_interval"),
        CheckConstraint(
            "active_duration_seconds IS NULL OR active_duration_seconds >= 0",
            name="ck_health_workout_duration",
        ),
        CheckConstraint(
            "energy_kcal IS NULL OR energy_kcal >= 0", name="ck_health_workout_energy"
        ),
        CheckConstraint(
            "distance_miles IS NULL OR distance_miles >= 0",
            name="ck_health_workout_distance",
        ),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_time = Column(HEALTH_TIMESTAMP, nullable=False)
    end_time = Column(HEALTH_TIMESTAMP, nullable=False)
    activity_type = Column(String(100), nullable=False)
    active_duration_seconds = Column(Float, nullable=True)
    energy_kcal = Column(Float, nullable=True)
    distance_miles = Column(Float, nullable=True)
    source = Column(String(50), default="apple_health", nullable=False)
    source_name = Column(String(255), nullable=True)
    external_id = Column(String(255), nullable=True)
    import_key = Column(String(64), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class HealthImportToken(Base):
    """A revocable credential scoped to Apple Health uploads only."""

    __tablename__ = "health_import_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_success_at = Column(DateTime, nullable=True)
    last_counts = Column(JSON, nullable=True)


class HealthShortcutProgress(Base):
    """Advance a category only after every acknowledged batch arrives."""

    __tablename__ = "health_shortcut_progress"
    __table_args__ = (
        Index("uq_user_shortcut_metric", "user_id", "metric", unique=True),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    metric = Column(String(40), nullable=False)
    completed_until = Column(HEALTH_TIMESTAMP, nullable=False)
    last_completed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class HealthShortcutBatch(Base):
    """Small delivery receipts, not additional copies of health samples."""

    __tablename__ = "health_shortcut_batches"
    __table_args__ = (
        Index(
            "uq_user_shortcut_batch", "user_id", "plan_hash", "batch_index", unique=True
        ),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_hash = Column(String(64), nullable=False)
    batch_index = Column(Integer, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    record_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class HealthNativeImport(Base):
    """A small import receipt without retaining the original private ZIP."""

    __tablename__ = "health_native_imports"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    counts = Column(JSON, nullable=False)


class EmailApproval(Base):
    """Verified membership addresses; never an administrator role."""

    __tablename__ = "email_approvals"
    email = Column(String(254), primary_key=True)
    verified_at = Column(DateTime, nullable=False)
    approved_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class EmailVerification(Base):
    """Expiring, hash-only links and send-limit receipts."""

    __tablename__ = "email_verifications"
    id = Column(Integer, primary_key=True)
    email = Column(String(254), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    request_key = Column(String(64), nullable=False, index=True)
