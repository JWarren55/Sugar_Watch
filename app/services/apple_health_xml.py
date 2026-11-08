"""Stream Apple's native ZIP export; retain supported individual records and workouts."""

import hashlib
import json
import zipfile
from contextlib import contextmanager
from xml.etree import ElementTree

from app.services.apple_health import HealthImportError, parse_export, stamp

XML_METRICS = {
    "HKCategoryTypeIdentifierSleepAnalysis": "sleep_analysis",
    "HKQuantityTypeIdentifierStepCount": "step_count",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy",
    "HKQuantityTypeIdentifierBodyMass": "weight",
    "HKQuantityTypeIdentifierHeartRate": "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "heart_rate_variability",
}
SLEEP = {
    "HKCategoryValueSleepAnalysisInBed": "in bed",
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "asleep",
    "HKCategoryValueSleepAnalysisAsleep": "asleep",
    "HKCategoryValueSleepAnalysisAwake": "awake",
    "HKCategoryValueSleepAnalysisAsleepCore": "core",
    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
}
MAX_XML_BYTES = 1024 * 1024 * 1024
MAX_ELEMENTS = 3000000


class BoundedXML:
    def __init__(self, stream):
        self.stream, self.total, self.tail = stream, 0, b""
        self.token_length = 0

    def read(self, size=-1):
        data = self.stream.read(min(size, 65536) if size >= 0 else 65536)
        self.total += len(data)
        if self.total > MAX_XML_BYTES:
            raise HealthImportError("The expanded export is too large (limit 1 GB).")
        # Native Apple exports contain a DTD declaration but do not need entities.
        # Reject entity declarations and non-UTF-8 encodings before feeding Expat.
        scan = (self.tail + data).upper()
        if b"<!ENTITY" in scan or b"\x00" in data:
            raise HealthImportError("The export contains unsupported XML declarations.")
        pieces = data.split(b">")
        if len(pieces) == 1:
            self.token_length += len(data)
        else:
            if self.token_length + len(pieces[0]) > 256 * 1024 or any(
                len(piece) > 256 * 1024 for piece in pieces[1:]
            ):
                raise HealthImportError("An XML record is too large.")
            self.token_length = len(pieces[-1])
        if self.token_length > 256 * 1024:
            raise HealthImportError("An XML record is too large.")
        self.tail = scan[-64:]
        return data


@contextmanager
def export_stream(file):
    try:
        with zipfile.ZipFile(file) as archive:
            entries = [
                entry
                for entry in archive.infolist()
                if entry.filename in ("apple_health_export/export.xml", "export.xml")
            ]
            if (
                len(entries) != 1
                or entries[0].file_size > MAX_XML_BYTES
                or entries[0].flag_bits & 1
            ):
                raise HealthImportError(
                    "Choose Apple's original export.zip containing export.xml (up to 1 GB expanded)."
                )
            with archive.open(entries[0]) as stream:
                yield BoundedXML(stream)
    except (zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError, OSError):
        raise HealthImportError(
            "This ZIP file could not be read. Export it again from Apple Health."
        )


def records_from_zip(file, stats):
    with export_stream(file) as stream:
        try:
            events = ElementTree.iterparse(stream, events=("start", "end"))
            _, root = next(events)
            if root.tag != "HealthData":
                raise HealthImportError("This is not an Apple Health export.")
            seen = 0
            depth = 1
            for event, node in events:
                if event == "start":
                    depth += 1
                    if depth > 64:
                        raise HealthImportError(
                            "The XML contains too many nested elements."
                        )
                else:
                    depth -= 1
                if event != "end" or node.tag not in (
                    "Record",
                    "Workout",
                    "ActivitySummary",
                    "ClinicalRecord",
                    "Correlation",
                    "ExportDate",
                    "Me",
                ):
                    continue
                seen += 1
                if seen > MAX_ELEMENTS:
                    raise HealthImportError(
                        "The export has too many records for one import."
                    )
                if node.tag == "Record":
                    name = XML_METRICS.get(node.get("type"))
                    if name:
                        row = {
                            "start": node.get("startDate"),
                            "end": node.get("endDate"),
                            "source": node.get("sourceName", ""),
                            "units": node.get("unit"),
                            "qty": node.get("value"),
                        }
                        if name == "sleep_analysis":
                            row["value"] = SLEEP.get(
                                node.get("value"), node.get("value")
                            )
                        parsed, _ = parse_export(
                            {"data": {"metrics": [{"name": name, "data": [row]}]}}
                        )
                        yield from parsed
                    else:
                        stats["unsupported"] += 1
                elif node.tag == "Workout":
                    source, start, end, activity = (
                        node.get(key, "")
                        for key in (
                            "sourceName",
                            "startDate",
                            "endDate",
                            "workoutActivityType",
                        )
                    )
                    # Stable across repeat native exports; original export has no universal UUID.
                    identifier = hashlib.sha256(
                        json.dumps(
                            [
                                source,
                                stamp(start).isoformat(),
                                stamp(end).isoformat(),
                                activity,
                            ]
                        ).encode()
                    ).hexdigest()
                    try:
                        duration = float(node.get("duration", "0"))
                        factor = {"s": 1, "sec": 1, "min": 60, "hr": 3600}[
                            node.get("durationUnit", "min")
                        ]
                    except (ValueError, KeyError):
                        raise HealthImportError(
                            "A workout has an unsupported duration."
                        )
                    workout = {
                        "id": identifier,
                        "name": activity.removeprefix("HKWorkoutActivityType"),
                        "start": start,
                        "end": end,
                        "duration": duration * factor,
                        "source": source,
                    }
                    for field, attr, unit_attr in (
                        (
                            "activeEnergyBurned",
                            "totalEnergyBurned",
                            "totalEnergyBurnedUnit",
                        ),
                        ("distance", "totalDistance", "totalDistanceUnit"),
                    ):
                        if node.get(attr) is not None:
                            workout[field] = {
                                "qty": node.get(attr),
                                "units": node.get(unit_attr),
                            }
                    # New exports can carry energy/distance as WorkoutStatistics children.
                    for stat in node.findall("WorkoutStatistics"):
                        kind = stat.get("type", "")
                        target = (
                            "activeEnergyBurned"
                            if kind.endswith("ActiveEnergyBurned")
                            else "distance"
                            if "Distance" in kind
                            else None
                        )
                        if (
                            target
                            and target not in workout
                            and stat.get("sum") is not None
                        ):
                            workout[target] = {
                                "qty": stat.get("sum"),
                                "units": stat.get("unit"),
                            }
                    parsed, _ = parse_export({"data": {"workouts": [workout]}})
                    yield from parsed
                # Only discard the finished top-level item, preserving workout children until parsed.
                node.clear()
                root.clear()
        except (ElementTree.ParseError, StopIteration, UnicodeError, ValueError):
            raise HealthImportError(
                "The export contains invalid or unsupported health records. Nothing was imported."
            )
