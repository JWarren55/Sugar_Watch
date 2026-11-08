"""Enter the food API key privately and verify it before saving."""

import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import set_key

from app.services.food_catalog import CatalogError, USDAClient


def main():
    if not sys.stdin.isatty():
        raise CatalogError("Run this setup in your own interactive terminal.")
    key = getpass.getpass("USDA FoodData Central API key (hidden): ").strip()
    if not key or key == "DEMO_KEY" or any(c.isspace() for c in key):
        raise CatalogError("Enter your own USDA API key, not the shared demo key.")
    USDAClient(key).search("apple")
    path = ROOT / ".env"
    if not path.is_file():
        raise CatalogError(
            "Application environment file is missing. Nothing was saved."
        )
    set_key(str(path), "USDA_API_KEY", key, quote_mode="always")
    path.chmod(0o600)
    print(
        "PASS: USDA API key verified and saved privately. Restart the web service to load it."
    )


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("Setup cancelled. No key was saved.", file=sys.stderr)
        raise SystemExit(1)
    except CatalogError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        print("Setup failed. Key and provider details omitted.", file=sys.stderr)
        raise SystemExit(1)
