"""Write the API's OpenAPI schema to a file (used to generate the dashboard's TypeScript types).

    uv run python scripts/export_openapi.py ../../apps/web/openapi.json

No database is needed; placeholder settings are used if none are set.
"""

from __future__ import annotations

import base64
import json
import os
import sys

os.environ.setdefault("MIXT_DATABASE_URL", "postgresql+psycopg://unused@localhost/unused")
os.environ.setdefault("MIXT_ENCRYPTION_KEYS", json.dumps({"schema-export": base64.b64encode(b"\0" * 32).decode()}))
os.environ.setdefault("MIXT_ACTIVE_ENCRYPTION_KEY_ID", "schema-export")
os.environ.setdefault("MIXT_ENV", "test")

from mixt.api.app import create_app


def main(path: str) -> None:
    schema = create_app().openapi()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(schema, fh, indent=2, sort_keys=True)
        fh.write("\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
