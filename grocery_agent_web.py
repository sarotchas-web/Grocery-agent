from __future__ import annotations

import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from grocery_agent.web_app import DEFAULT_PROFILE_PATH, run


def main() -> int:
    parser = argparse.ArgumentParser(prog="grocery-agent-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--profile-path", default=str(DEFAULT_PROFILE_PATH))
    args = parser.parse_args()
    run(host=args.host, port=args.port, profile_path=Path(args.profile_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
