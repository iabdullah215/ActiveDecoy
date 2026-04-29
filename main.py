"""Project launcher for ActiveDecoy.

This root entrypoint starts the FastAPI application defined in app/main.py so
the whole project can be launched from a single command.
"""

from __future__ import annotations

import argparse
import socket

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch ActiveDecoy")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address for the web server")
    parser.add_argument("--port", default=8000, type=int, help="Port for the web server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--strict-port", action="store_true", help="Fail instead of auto-selecting a free port")
    return parser


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex((host, port)) != 0


def _select_port(host: str, port: int, strict_port: bool) -> int:
    if _port_is_available(host, port):
        return port

    if strict_port:
        raise RuntimeError(f"Port {port} is already in use on {host}.")

    candidate = port + 1
    while candidate < port + 100:
        if _port_is_available(host, candidate):
            print(f"Port {port} is in use, falling back to {candidate}.")
            return candidate
        candidate += 1

    raise RuntimeError(f"No free port found near {port} on {host}.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    selected_port = _select_port(args.host, args.port, args.strict_port)
    uvicorn.run("app.main:app", host=args.host, port=selected_port, reload=args.reload)


if __name__ == "__main__":
    main()
