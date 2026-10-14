"""`calcview` command line. Import, audit and export commands arrive in M3/M4."""
import argparse

import uvicorn

from app.main import HOST


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calcview")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="start the web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run("app.main:app", host=HOST, port=args.port)
    return 0
