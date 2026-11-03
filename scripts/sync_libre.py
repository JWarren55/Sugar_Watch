"""Run once; systemd supplies the polling schedule and protected configuration."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from libre_polling import PollDeferred
from libre_sync import SyncConfig, SyncError, save_readings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate without writing readings",
    )
    parser.add_argument(
        "--env-file", type=Path, help="Read a private local Libre configuration file"
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(
            os.environ.get(
                "LIBRE_SYNC_STATE",
                str(Path.home() / ".local/state/sugar-watch/libre-session.json"),
            )
        ),
    )
    args = parser.parse_args()
    try:
        values = dict(os.environ)
        if args.env_file:
            import stat

            from dotenv import dotenv_values

            info = args.env_file.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise SyncError(
                    "Local Libre configuration must be owned by you with permissions 0600."
                )
            values.update(dotenv_values(args.env_file, interpolate=False))
        config = SyncConfig.from_mapping(values)
        from libre_polling import cached_fetch, session_state

        with session_state(args.state_file) as state:
            with httpx.Client(
                timeout=20, follow_redirects=False, trust_env=False
            ) as client:
                rows = cached_fetch(config, client, state)
        if args.dry_run:
            print(f"Libre sync dry run: {len(rows)} validated readings; nothing saved.")
            return 0
        from database import SessionLocal

        added, skipped = save_readings(SessionLocal, config.user_id, rows)
        print(f"Libre sync succeeded: {added} added; {skipped} already present.")
        return 0
    except PollDeferred as exc:
        print(f"Libre sync deferred: {exc}")
        return 0
    except SyncError as exc:
        print(f"Libre sync failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # Exception strings may contain URLs, SQL parameters, or provider payloads.
        print(
            "Libre sync failed: unexpected response or database failure. Check configuration and release compatibility.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
