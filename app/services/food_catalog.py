"""USDA FoodData Central search and explicit per-100-g nutrition mapping."""

import re
import unicodedata
from math import isfinite

import httpx

from app.services.nutrition import NUTRIENT_UNITS


class CatalogError(Exception):
    pass


NUTRIENTS = {
    1008: "calories",
    2047: "calories",
    2048: "calories",
    1003: "protein",
    1004: "fat",
    1005: "carbs",
    1079: "fiber",
    2000: "sugar",
    1235: "added_sugar",
    1093: "sodium",
    1253: "cholesterol",
    1258: "saturated_fat",
    1257: "trans_fat",
    1114: "vitamin_d",
    1087: "calcium",
    1089: "iron",
    1092: "potassium",
    1057: "caffeine",
}
DATA_TYPES = ("Branded", "Foundation", "SR Legacy", "Survey (FNDDS)")


def normalize_brand(value):
    value = value.strip()
    key = re.sub(r"[^a-z0-9]", "", value.casefold())
    return {
        "walmartgreatvalue": "Great Value",
        "walmarkgreatvalue": "Great Value",
        "greatvalue": "Great Value",
        "mcdonalds": "McDonald's",
    }.get(key, value)


def normalize_barcode(value):
    # Keep leading zeroes; accept spaces/hyphens from packaging, never a URL.
    value = re.sub(r"[\s-]", "", value)
    if not value.isascii() or not value.isdigit() or len(value) not in (8, 12, 13, 14):
        raise CatalogError("Enter an 8, 12, 13, or 14-digit product barcode.")
    check = sum(
        int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(value[:-1]))
    )
    if (10 - check % 10) % 10 != int(value[-1]):
        raise CatalogError(
            "The barcode check digit is invalid. Check the numbers and try again."
        )
    return value


def brand_words(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    # McDonalds and McDonald's should compare identically.
    return re.findall(r"[a-z0-9]+", value.replace("'", "").replace("’", ""))


def food_values(raw):
    if not isinstance(raw, dict) or raw.get("dataType") not in DATA_TYPES:
        raise CatalogError(
            "This food type is not supported yet. Choose another result."
        )
    name = str(raw.get("description") or "").strip()
    if not name or not isinstance(raw.get("foodNutrients"), list):
        raise CatalogError("This food does not contain usable nutrition information.")
    values = dict(
        name=name[:200],
        brand=str(raw.get("brandName") or raw.get("brandOwner") or "").strip()[:200]
        or None,
        serving_size=100.0,
        serving_unit="g",
        barcode=str(raw.get("gtinUpc") or "").strip()[:50] or None,
    )
    values.update({name: None for name in NUTRIENT_UNITS})
    # Use one energy measure, preferring the standard energy nutrient over alternatives.
    valid = [
        item
        for item in raw["foodNutrients"]
        if isinstance(item, dict) and isinstance(item.get("nutrient"), dict)
    ]
    nutrients = sorted(
        valid,
        key=lambda item: {1008: 0, 2047: 1, 2048: 2}.get(
            item.get("nutrient", {}).get("id"), 3
        ),
    )
    for item in nutrients:
        nutrient = item.get("nutrient", {})
        field = NUTRIENTS.get(nutrient.get("id"))
        if field is None or values[field] is not None or item.get("amount") is None:
            continue
        unit = (
            str(nutrient.get("unitName") or "")
            .strip()
            .lower()
            .replace("µ", "u")
            .replace("μ", "u")
        )
        unit = {"ug": "mcg"}.get(unit, unit)
        target = NUTRIENT_UNITS[field]
        try:
            amount = float(item["amount"])
        except (TypeError, ValueError):
            raise CatalogError(
                "This food has an invalid nutrient amount. Choose another result."
            )
        if isinstance(item["amount"], bool) or not isfinite(amount) or amount < 0:
            raise CatalogError(
                "This food has an invalid nutrient amount. Choose another result."
            )
        if unit != target:
            mass = {"g": 1, "mg": 0.001, "mcg": 0.000001}
            if unit not in mass or target not in mass:
                continue
            amount *= mass[unit] / mass[target]
        if not isfinite(amount):
            raise CatalogError(
                "This food has an invalid nutrient amount. Choose another result."
            )
        values[field] = amount
    if all(values[field] is None for field in NUTRIENT_UNITS):
        raise CatalogError(
            "No supported nutrient amounts were found. Choose another result."
        )
    return values


class USDAClient:
    def __init__(self, key, client=None):
        self.key, self.client = key, client

    def request(self, path, params=None):
        if not self.key:
            raise CatalogError(
                "Food database search is not available yet. You can still add custom foods."
            )

        def send(client):
            try:
                response = client.get(
                    "https://api.nal.usda.gov/fdc/v1/" + path,
                    params={"api_key": self.key, **(params or {})},
                )
                if response.status_code == 429:
                    raise CatalogError(
                        "The food database is busy. Please try again later."
                    )
                if response.status_code == 404:
                    raise CatalogError(
                        "This food is no longer available. Try another search."
                    )
                if response.status_code != 200:
                    raise CatalogError(
                        "The food database could not complete this request. Please try again later."
                    )
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError()
                return result
            except (httpx.HTTPError, ValueError):
                # Exceptions can contain API-key URLs; never expose or log them.
                raise CatalogError(
                    "Unable to reach the food database. Your saved foods are still available."
                )

        if self.client is not None:
            return send(self.client)
        with httpx.Client(
            timeout=10, follow_redirects=False, trust_env=False
        ) as client:
            return send(client)

    def search(self, query, page=1, *, brand="", kind="all"):
        brand = normalize_brand(brand)
        params = {
            "query": " ".join(filter(None, (query, brand))),
            "pageSize": 10,
            "pageNumber": page,
        }
        if kind == "branded":
            params["dataType"] = "Branded"
        elif kind == "common":
            params["dataType"] = ",".join(DATA_TYPES[1:])
        # Require the food terms as well as brand terms instead of unrelated OR hits.
        params["requireAllWords"] = "true"
        raw = self.request("foods/search", params)
        foods, more = self.search_results(raw, page)
        if brand:
            # Match the label brand and owner; do not confuse Great Value with Walmart's owner name.
            wanted = brand_words(brand)
            foods.sort(
                key=lambda item: (
                    not all(
                        word
                        in brand_words(
                            item["brand"] + " " + item["owner"] + " " + item["name"]
                        )
                        for word in wanted
                    )
                )
            )
        return foods, more

    def search_results(self, raw, page):
        if not isinstance(raw.get("foods"), list):
            raise CatalogError(
                "The food database returned an unsupported result. Please try again later."
            )
        foods = []
        for item in raw["foods"][:10]:
            if (
                not isinstance(item, dict)
                or item.get("dataType") not in DATA_TYPES
                or type(item.get("fdcId")) is not int
            ):
                continue
            foods.append(
                dict(
                    id=item["fdcId"],
                    name=str(item.get("description") or "")[:300],
                    brand=str(item.get("brandName") or item.get("brandOwner") or "")[
                        :200
                    ],
                    owner=str(item.get("brandOwner") or "")[:200],
                    barcode=str(item.get("gtinUpc") or "")[:50],
                    kind=item["dataType"],
                )
            )
        pages = raw.get("totalPages", 1)
        return foods, type(pages) is int and page < min(pages, 100)

    def barcode(self, value, page=1):
        code = normalize_barcode(value)
        raw = self.request(
            "foods/search",
            {"query": code, "dataType": "Branded", "pageSize": 10, "pageNumber": page},
        )
        foods, more = self.search_results(raw, page)
        # USDA's search can return fuzzy matches. Only show the identical GTIN,
        # with zero padding allowed between UPC-A, EAN-13 and GTIN-14 forms.
        foods = [
            food
            for food in foods
            if food["barcode"].isascii()
            and food["barcode"].isdigit()
            and len(food["barcode"]) in (8, 12, 13, 14)
            and food["barcode"].zfill(14) == code.zfill(14)
        ]
        return foods, more

    def food(self, fdc_id):
        raw = self.request(f"food/{fdc_id}")
        if type(raw.get("fdcId")) is not int or raw.get("fdcId") != fdc_id:
            raise CatalogError(
                "The food response did not match your selection. Search again."
            )
        return food_values(raw)
