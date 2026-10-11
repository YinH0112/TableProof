import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

from .api import create_app


def main():
    parser = argparse.ArgumentParser(description="TableProof Research local workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", args.port))
    except OSError:
        parser.error(f"port {args.port} is occupied; choose another with --port")

    if not args.no_browser:
        def open_browser():
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", args.port), timeout=.2):
                        webbrowser.open(f"http://127.0.0.1:{args.port}")
                        return
                except OSError:
                    time.sleep(.1)
        threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
