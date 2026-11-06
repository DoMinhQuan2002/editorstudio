from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from mediastudio.api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Media Studio local backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--token", default=os.environ.get("MEDIASTUDIO_SESSION_TOKEN", ""))
    parser.add_argument("--data-directory", required=True, type=Path)
    parser.add_argument("--models-directory", required=True, type=Path)
    args = parser.parse_args()
    if not args.token:
        parser.error("a session token must be supplied by the desktop host")

    app = create_app(args.token, args.data_directory, args.models_directory)
    server = uvicorn.Server(
        uvicorn.Config(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    )
    app.state.uvicorn_server = server
    server.run()


if __name__ == "__main__":
    main()
