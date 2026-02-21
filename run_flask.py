from __future__ import annotations

import argparse

from flask_app import create_app


def main() -> None:
    """Run PDF Studio in dev mode or behind Waitress for production."""
    parser = argparse.ArgumentParser(description="Run PDF Studio Flask app")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Use Flask dev server with debug reload (default uses Waitress).",
    )
    args = parser.parse_args()
    app = create_app()

    if args.dev:
        app.run(host=args.host, port=args.port, debug=True)
        return

    try:
        from waitress import serve
    except ImportError:
        app.run(host=args.host, port=args.port, debug=False)
        return

    serve(app, host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
