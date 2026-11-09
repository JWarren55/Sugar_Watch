"""Selected U.S. menu items from official restaurant nutrition guides."""

from app.services.food_catalog import brand_words
from app.services.nutrition import NUTRIENT_UNITS

ARBYS = "Arby's"
ARBYS_SOURCE = (
    "https://assets.ctfassets.net/30q5w5l98nbx/6CplhZeKpu7X9ts2pSE3Lg/"
    "624b24407875e1dbdf6f07f0da28897e/Arbys_Nutritional_and_Allergen_NOV_2026.pdf"
)
ARBYS_SOURCE_LABEL = "Arby's U.S. Nutrition & Allergen Guide, November 2026"
ARBYS_ALIASES = {"arbys", "arby"}

# The Crispy Chicken section of the guide lists values for a full menu serving.
# Columns: serving g, kcal, fat g, saturated fat g, trans fat g, cholesterol mg,
# sodium mg, carbs g, fiber g, sugar g, protein g.
ARBYS_CHICKEN = {
    "crispy-chicken": (
        "Crispy Chicken Sandwich",
        (240, 530, 22, 4.5, 0, 50, 1410, 59, 4, 13, 24),
    ),
    "buffalo-chicken": (
        "Buffalo Chicken Sandwich",
        (228, 530, 22, 4.5, 0, 45, 2100, 59, 4, 12, 24),
    ),
    "chicken-bacon-swiss": (
        "Chicken Bacon Swiss Sandwich",
        (272, 650, 30, 9.5, 0, 75, 1760, 61, 4, 14, 35),
    ),
    "chicken-cordon-bleu": (
        "Chicken Cordon Bleu Sandwich",
        (233, 650, 30, 9, 0, 85, 1790, 59, 4, 11, 35),
    ),
    "chicken-tenders-3pc": (
        "Chicken Tenders (3 piece)",
        (129, 370, 18, 3, 0, 60, 1190, 28, 2, 0, 23),
    ),
    "chicken-tenders-5pc": (
        "Chicken Tenders (5 piece)",
        (215, 610, 30, 4.5, 0, 100, 1990, 47, 3, 0, 39),
    ),
}
MENU_FIELDS = (
    "serving_size",
    "calories",
    "fat",
    "saturated_fat",
    "trans_fat",
    "cholesterol",
    "sodium",
    "carbs",
    "fiber",
    "sugar",
    "protein",
)


def search_restaurant_menu(query, brand):
    terms = set(brand_words(query))
    brand_terms = set(brand_words(brand))
    if brand_terms:
        if not brand_terms <= ARBYS_ALIASES:
            return []
    elif not terms & ARBYS_ALIASES:
        return []
    terms -= ARBYS_ALIASES
    return [
        {
            "name": name,
            "brand": ARBYS,
            "kind": "Restaurant menu",
            "barcode": None,
            "review_url": f"/food/catalog/restaurant/arbys-{item_id}",
        }
        for item_id, (name, _) in ARBYS_CHICKEN.items()
        if terms <= set(brand_words(name) + brand_words(item_id))
    ]


def restaurant_food(external_id):
    if not external_id.startswith("arbys-"):
        return None
    item = ARBYS_CHICKEN.get(external_id.removeprefix("arbys-"))
    if item is None:
        return None
    name, amounts = item
    return {
        **dict.fromkeys(NUTRIENT_UNITS),
        **dict(zip(MENU_FIELDS, amounts, strict=True)),
        "name": name,
        "brand": ARBYS,
        "serving_unit": "g",
    }
