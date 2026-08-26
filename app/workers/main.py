import asyncio
import logging
import signal
import time

from redis.asyncio import from_url
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config.settings import get_settings
from app.workers.handlers import default_handlers
from app.workers.worker import MediaWorker

# ARQ-07: o worker não pode morrer na primeira falha de conexão com o Redis —
# o docker compose sobe Postgres/Redis em paralelo e um restart rápido pode
# iniciar o worker antes do container aceitar conexões.
REDIS_CONNECT_MAX_ATTEMPTS = 3
REDIS_CONNECT_RETRY_BASE_SECONDS = 5.0
REDIS_RETRY_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
    RedisConnectionError,
    RedisTimeoutError,
)


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
    for attempt in range(1, REDIS_CONNECT_MAX_ATTEMPTS + 1):
        try:
            asyncio.run(run_worker())
            return
        except REDIS_RETRY_EXCEPTIONS as exc:
            # ARQ-07: o Redis sobe em paralelo ao worker (docker compose);
            # um restart rápido pode deixar o worker iniciar antes do
            # container responder. Retry com backoff em vez de desistir.
            if attempt >= REDIS_CONNECT_MAX_ATTEMPTS:
                logging.error(
                    "worker_redis_connect_failed attempts=%d error=%s", attempt, exc
                )
                raise
            delay = REDIS_CONNECT_RETRY_BASE_SECONDS * attempt
            logging.warning(
                "worker_redis_connect_retry attempt=%d/%d delay=%.0fs error=%s",
                attempt,
                REDIS_CONNECT_MAX_ATTEMPTS,
                delay,
                exc,
            )
            time.sleep(delay)


if __name__ == "__main__":
    main()
