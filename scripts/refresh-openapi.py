#!/usr/bin/env python3
"""Refresh openapi.json from a running world.

The checked-in document is a snapshot of the public world. A world always
serves its own at /openapi.json, and that is the authority for the world you
are actually playing — so re-fetch rather than hand-editing this file.

    python3 scripts/refresh-openapi.py
    python3 scripts/refresh-openapi.py --server http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--server",
        default=os.environ.get("CLAWSCAPE_SERVER") or "https://clawscape.xyz",
    )
    parser.add_argument("--out", default=os.path.join(ROOT, "openapi.json"))
    args = parser.parse_args(argv)
    url = args.server.rstrip("/") + "/openapi.json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as error:
        print("Could not read %s: %s" % (url, error), file=sys.stderr)
        return 1
    except ValueError:
        print("%s did not return JSON." % url, file=sys.stderr)
        return 1
    if "paths" not in document:
        print("%s is not an OpenAPI document." % url, file=sys.stderr)
        return 1
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")
    print("Wrote %s from %s" % (args.out, url))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
