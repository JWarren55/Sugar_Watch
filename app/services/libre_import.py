"""Parse English LibreView CSV exports; never retain the uploaded source file."""

import csv
import hashlib
import io
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse_libreview(content, timezone_name, date_order):
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Choose a valid IANA timezone, such as America/Chicago.")
    if date_order not in ("MDY", "DMY"):
        raise ValueError("Choose month/day/year or day/month/year.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Upload a UTF-8 CSV downloaded from LibreView.")
    records = list(csv.reader(io.StringIO(text)))
    start = next(
        (
            i
            for i, r in enumerate(records[:20])
            if "Device Timestamp" in r and "Record Type" in r
        ),
        None,
    )
    if start is None:
        raise ValueError(
            "Expected an English LibreView CSV with Device Timestamp and Record Type columns."
        )
    header = records[start]
    if len(set(header)) != len(header):
        raise ValueError("Duplicate CSV column names are not supported.")
    expected = {"Device", "Serial Number", "Device Timestamp", "Record Type"}
    if not expected.issubset(header):
        raise ValueError("The export is missing device identification columns.")
    glucose_columns = [
        c
        for c in header
        if c
        in (
            "Historic Glucose mg/dL",
            "Scan Glucose mg/dL",
            "Historic Glucose mmol/L",
            "Scan Glucose mmol/L",
        )
    ]
    if not glucose_columns:
        raise ValueError("The export has no supported glucose columns.")
    formats = (
        ["%m-%d-%Y %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p"]
        if date_order == "MDY"
        else ["%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p"]
    )
    formats += (
        ["%m-%d-%Y %I:%M %p", "%m-%d-%Y %I:%M:%S %p"]
        if date_order == "MDY"
        else ["%d-%m-%Y %I:%M %p", "%d-%m-%Y %I:%M:%S %p"]
    )
    formats += ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]
    parsed, ignored = {}, 0
    for line, values in enumerate(records[start + 1 :], start + 2):
        if not any(values):
            continue
        if len(values) != len(header):
            raise ValueError(f"Row {line}: column count does not match the header.")
        row = dict(zip(header, values))
        kind = row["Record Type"].strip()
        if kind not in ("0", "1"):
            ignored += 1
            continue
        prefix = "Historic" if kind == "0" else "Scan"
        columns = [
            c for c in glucose_columns if c.startswith(prefix) and row[c].strip()
        ]
        if len(columns) != 1:
            raise ValueError(
                f"Row {line}: expected one numeric {prefix.lower()} glucose value."
            )
        try:
            value = Decimal(row[columns[0]].strip())
            if columns[0].endswith("mmol/L"):
                value *= Decimal("18.0182")
            if not value.is_finite() or not Decimal(20) <= value <= Decimal(600):
                raise ValueError()
            glucose = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError):
            raise ValueError(
                f"Row {line}: glucose must be a numeric value between 20 and 600 mg/dL."
            )
        stamp = None
        for fmt in formats:
            try:
                stamp = datetime.strptime(row["Device Timestamp"].strip(), fmt)
                break
            except ValueError:
                pass
        if stamp is None:
            raise ValueError(
                f"Row {line}: unsupported timestamp for the chosen date order."
            )
        # Local exports lack an offset. Reject DST folds/gaps rather than invent an instant.
        from datetime import timezone

        aware = stamp.replace(tzinfo=zone)
        if aware.utcoffset() != stamp.replace(tzinfo=zone, fold=1).utcoffset():
            raise ValueError(
                f"Row {line}: timestamp is ambiguous or missing during a daylight-saving change."
            )
        utc = aware.astimezone(timezone.utc).replace(tzinfo=None)
        identity = "|".join(
            (row["Device"].strip(), row["Serial Number"].strip(), utc.isoformat(), kind)
        )
        key = hashlib.sha256(identity.encode()).hexdigest()
        item = {
            "timestamp": utc,
            "glucose": glucose,
            "source": "libreview",
            "import_key": key,
        }
        if key in parsed and parsed[key] != item:
            raise ValueError(
                f"Row {line}: conflicting values for the same device reading."
            )
        parsed[key] = item
    if not parsed:
        raise ValueError("No historic or scanned glucose readings were found.")
    return list(parsed.values()), ignored
