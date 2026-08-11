"""Write the edge's OpenAPI schema to a file.

The front end generates its TypeScript types from this, so a renamed field
shows up as a red build there rather than as `undefined` at runtime. Running it
needs no server, no GPU and no Google account: the app is built with stub
collaborators, because the schema depends only on the route signatures.

    python api/tools/dump_openapi.py web/src/app/core/contract/openapi.json

The output is committed. Generating it during the web build instead would mean
the front end could not be built without a working Python environment, which is
the opposite of what the split is for.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.jobs import JobRunner
from app.main import create_app
from app.store import open_store
from app.users import open_users

# Stand-ins for the pipeline's own lists. The schema does not carry their
# values, only the shapes of the requests and replies, so plausible names are
# enough and no import of the pipeline is needed.
BANKS = {"curated": "words_hq4", "muslimbank": "words_muslim"}
LEVELS = ("conservative", "wild")


def _never_called(url: str) -> Path:
    raise AssertionError("dumping the schema must not fetch a song")


def schema() -> dict:
    # The store holds its connection open and offers no close, so on Windows
    # the file is still locked when the directory is removed. The schema is
    # already in hand by then, and a leftover temp file is not worth widening
    # the store's surface for.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = open_store(Path(tmp) / "schema.sqlite3")
        app = create_app(
            settings=load_settings({}),
            runner=JobRunner(on_update=lambda _job: None),
            store=store,
            users=open_users(store.connection),
            banks=BANKS,
            standardised_suffix=".std",
            levels=LEVELS,
            # Required, and never called: the schema comes from the route
            # signatures, so nothing here fetches anything. It raises rather
            # than returning a plausible path, so a future change that does
            # reach it says so instead of writing somewhere unexpected.
            prepare_song=_never_called,
        )
        return app.openapi()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2

    out = Path(args[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    # Sorted and newline-terminated so regenerating an unchanged schema
    # produces no diff, which is what makes a stale-contract check possible.
    out.write_text(json.dumps(schema(), indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
