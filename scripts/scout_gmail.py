#!/usr/bin/env python3
"""Homestead Scout Gmail importer.

    scout_gmail.py authorize   one-time interactive OAuth (prints a URL, no secrets)
    scout_gmail.py dry-run     read Gmail and report; writes no discovery, sighting, or receipt
    scout_gmail.py run         read Gmail and import

Exit codes: 0 success, 1 run completed with per-message errors, 2 usage,
3 no verified alert adapter is registered, 4 the private Scout database is unreachable.

Token refresh, stated honestly: the stored token is refreshed automatically before each
run when it is within 60 seconds of expiry. Google issues a refresh_token only on a
consent-prompt authorization, so if the token file is ever replaced by one without a
refresh_token, unattended runs fail loudly and `authorize` must be run again.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scout import db, gmail  # noqa: E402
from scout.adapters import ADAPTERS  # noqa: E402
from scout.importer import NoAdaptersConfigured, run_import  # noqa: E402

DB_PATH = os.environ.get("HOMESTEAD_SCOUT_DB", "/var/lib/homestead/scout/scout.sqlite3")
CREDENTIALS = os.environ.get("HOMESTEAD_SCOUT_GMAIL_CREDENTIALS", gmail.DEFAULT_CREDENTIALS_PATH)
TOKEN = os.environ.get("HOMESTEAD_SCOUT_GMAIL_TOKEN", gmail.DEFAULT_TOKEN_PATH)


def main(argv):
    command = argv[1] if len(argv) > 1 else "run"
    if command not in ("authorize", "run", "dry-run"):
        print("usage: scout_gmail.py authorize|run|dry-run", file=sys.stderr)
        return 2

    if command == "authorize":
        result = gmail.authorize(CREDENTIALS, TOKEN)
        print(json.dumps({"ok": True, **result}, indent=2))
        return 0

    # Reported before the credential check on purpose. Having no verified alert template
    # is the deeper blocker, and leading with "missing client_secret.json" would suggest
    # that authorizing is the next step when it would change nothing.
    if not ADAPTERS:
        print(json.dumps({
            "ok": False, "blocked": "no_verified_adapter",
            "error": ("no verified Zillow/Redfin alert template is registered. Observe one "
                      "real alert per source, then add its adapter in scout/adapters.py."),
        }, indent=2), file=sys.stderr)
        return 3

    try:
        conn = db.connect(DB_PATH)
    except OSError as exc:
        # Almost always "run this as the homestead account". A raw PermissionError
        # traceback at 2am says far less than the path and the reason.
        print(json.dumps({
            "ok": False, "error": f"cannot open the Scout database at {DB_PATH}: {exc}",
            "hint": "the importer runs as the homestead account; try sudo -u homestead",
        }, indent=2), file=sys.stderr)
        return 4

    try:
        auth = gmail.load_auth(CREDENTIALS, TOKEN)
        summary = run_import(conn, auth, dry_run=(command == "dry-run"))
    except NoAdaptersConfigured as exc:
        print(json.dumps({"ok": False, "blocked": "no_verified_adapter", "error": str(exc)},
                         indent=2), file=sys.stderr)
        return 3
    except gmail.GmailError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(json.dumps(summary, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
