"""CLI entry point for the Google Calendar MCP server."""

from __future__ import annotations

import argparse

import uvicorn

from .authorize import main as authorize_main
from .config import DEFAULT_HOST, DEFAULT_PORT
from .server import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m calendar_mcp",
        description="Run the Google Calendar MCP server or authorization helper.",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the MCP server (default).")
    serve_parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host interface to bind (default: {DEFAULT_HOST}).",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port to listen on (default: {DEFAULT_PORT}).",
    )

    subparsers.add_parser(
        "authorize",
        help="Run the interactive OAuth flow to grant Google Calendar access.",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command or "serve"

    if command == "authorize":
        authorize_main()
        return

    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
