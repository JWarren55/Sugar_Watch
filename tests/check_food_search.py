"""Brand/restaurant search, barcode validation, exact matches, and safe rendering."""

import runpy
from unittest.mock import patch

import httpx

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app = state["app"]

from app.routes import food_catalog as routes
from app.services.food_catalog import CatalogError, USDAClient, normalize_barcode

calls = []
product = dict(
    fdcId=12345,
    dataType="Branded",
    description="Fixture cheddar",
    brandName="Great Value",
    brandOwner="Wal-Mart Stores, Inc.",
    gtinUpc="00036000291452",
)


def respond(request):
    params = request.url.params
    calls.append(params)
    query = params["query"]
    if query.isdigit():
        # Near matches must not appear for a scanned product.
        foods = [product, dict(product, fdcId=54321, gtinUpc="036000291469")]
    else:
        foods = [
            dict(product, fdcId=54321, brandName="Other Brand", brandOwner="Other"),
            product,
        ]
    return httpx.Response(200, json={"foods": foods, "totalPages": 3})


with httpx.Client(transport=httpx.MockTransport(respond)) as external:
    provider = USDAClient("fixture-key", external)
    matches, more = provider.search("cheese", brand="Walmark Great Value")
    assert calls[-1]["query"] == "cheese Great Value"
    assert calls[-1]["requireAllWords"] == "true"
    assert "dataType" not in calls[-1]
    assert matches[0]["brand"] == "Great Value" and more
    provider.search("chicken", brand="Mcdonalds")
    assert calls[-1]["query"] == "chicken McDonald's"
    # Restaurant entries can be SR Legacy, not Branded.
    assert "dataType" not in calls[-1]
    provider.search("cheese", kind="common")
    assert calls[-1]["dataType"] == "Foundation,SR Legacy,Survey (FNDDS)"
    provider.search("cheese", kind="branded")
    assert calls[-1]["dataType"] == "Branded"
    for code in ("036000291452", "0036000291452", "00036000291452", "0 36000-29145 2"):
        matches, more = provider.barcode(code)
        assert [item["id"] for item in matches] == [12345]
    before = len(calls)
    for code in (
        "036000291453",
        "123",
        "https://example.com/036000291452",
        "０３６０００２９１４５２",
        "",
        "1e10",
    ):
        try:
            provider.barcode(code)
        except CatalogError:
            pass
        else:
            raise AssertionError("Invalid barcode accepted")
    assert len(calls) == before
    assert normalize_barcode("96385074") == "96385074"
    with (
        TestClient(app) as client,
        patch.object(routes, "client", return_value=provider),
    ):
        sign_in(client, 1)
        response = client.get(
            "/food/catalog",
            params={
                "q": "cheese",
                "brand": "Walmart Great Value",
                "kind": "all",
                "page": 2,
            },
        )
        assert response.status_code == 200
        assert "brand=Great%20Value" in response.text
        assert "page=3" in response.text and 'name="brand"' in response.text
        response = client.get("/food/catalog", params={"q": "Mcdonalds, chicken"})
        assert calls[-1]["query"] == "chicken McDonald's"
        response = client.get("/food/catalog", params={"barcode": "036000291452"})
        assert (
            "/food/catalog/12345" in response.text
            and "/food/catalog/54321" not in response.text
        )
        assert "barcode=036000291452" in response.text
        assert "fixture-key" not in response.text
        response = client.get("/food/catalog", params={"barcode": "036000291453"})
        assert "check digit" in response.text
        assert (
            client.get("/food/catalog", params={"brand": "a" * 101}).status_code == 422
        )
        assert client.get("/food/catalog?kind=unknown").status_code == 422
        response = client.get(
            "/food/catalog", params={"brand": "<script>alert(1)</script>"}
        )
        assert "<script>alert(1)</script>" not in response.text
        assert "media-src 'self' blob:" in response.headers["content-security-policy"]
        for resource in (
            "food_search.js",
            "food_search.css",
            "vendor/zxing-browser/zxing-browser.min.js",
        ):
            assert client.get("/static/" + resource).status_code == 200
    with TestClient(app) as anonymous:
        assert anonymous.get("/food/catalog", follow_redirects=False).status_code == 303

print(
    "PASS: brand/restaurant queries, common/branded filters, aliases, pagination, barcode checksums/zero padding/exact matching, validation and escaping."
)
