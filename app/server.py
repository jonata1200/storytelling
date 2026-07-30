import argparse
import asyncio
import sys

import uvicorn


def configure_windows_event_loop() -> None:
    if sys.platform != "win32":
        return
    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is not None:
        asyncio.set_event_loop_policy(selector_policy())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Storytelling Studio server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    configure_windows_event_loop()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
