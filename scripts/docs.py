"""Build or preview the Japanese and English docs side by side under site/.

    uv run --group docs python scripts/docs.py build   # strict build of every language
    uv run --group docs python scripts/docs.py serve   # build, then serve site/ on :8000

The language switcher links ../ja/ and ../en/, so it only works when both are built.
For live reload of one language use `zensical serve` (-f mkdocs.en.yml for English).
"""

from __future__ import annotations

import argparse
import functools
import http.server
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
CONFIGS = {"ja": "mkdocs.yml", "en": "mkdocs.en.yml"}

# Visitors to site/ land on the language their browser prefers (English otherwise).
REDIRECT = """<!doctype html>
<html><head><meta charset="utf-8"><title>roboloom</title>
<meta http-equiv="refresh" content="0; url=en/">
<script>
location.replace((navigator.language || "").startsWith("ja") ? "ja/" : "en/");
</script></head>
<body><a href="ja/">日本語</a> / <a href="en/">English</a></body></html>
"""


def build() -> None:
    for config in CONFIGS.values():
        subprocess.run(
            [sys.executable, "-m", "zensical", "build", "--strict", "-f", config],
            cwd=ROOT,
            check=True,
        )
    (SITE / "index.html").write_text(REDIRECT, encoding="utf-8")


def serve(port: int) -> None:
    build()
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(SITE)
    )
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Serving http://127.0.0.1:{port}/")
        server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["build", "serve"])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "build":
        build()
    else:
        serve(args.port)


if __name__ == "__main__":
    main()
