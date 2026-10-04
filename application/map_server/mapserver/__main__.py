# __main__.py
"""Run the map server locally: python -m mapserver (from application/map_server)."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "mapserver.app:create_app",
        factory=True,
        host=os.environ.get("MAP_SERVER_HOST", "127.0.0.1"),
        port=int(os.environ.get("MAP_SERVER_PORT", "8080")),
        server_header=False,
    )


if __name__ == "__main__":
    main()
