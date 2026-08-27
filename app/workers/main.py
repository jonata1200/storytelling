import asyncio
import logging
import signal

from redis.asyncio import from_url

from app.config.settings import get_settings
from app.workers.handlers import default_handlers
from app.workers.worker import MediaWorker


async def run_worker() -> None:
    settings = get_settings()
    redis = from_url(settings.redis_url)
    worker = MediaWorker(redis, settings, default_handlers())
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, worker.stopping.set)
            except NotImplementedError:
                pass
    try:
        await worker.run()
    finally:
        await redis.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
