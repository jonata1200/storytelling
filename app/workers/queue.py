import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ResponseError


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    job_id: UUID


class RedisJobQueue:
    def __init__(self, redis: Redis, *, stream: str, group: str) -> None:
        self.redis = redis
        self.stream = stream
        self.group = group

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, job_id: UUID) -> str:
        message_id = await self.redis.xadd(self.stream, {"job_id": str(job_id)})
        return _text(message_id)

    async def dequeue(self, consumer: str, *, block_ms: int = 5000) -> QueueMessage | None:
        rows = await self.redis.xreadgroup(
            self.group,
            consumer,
            {self.stream: ">"},
            count=1,
            block=block_ms,
        )
        return _first_message(rows)

    async def reclaim(
        self, consumer: str, *, min_idle_ms: int, count: int = 10
    ) -> list[QueueMessage]:
        response = await self.redis.xautoclaim(
            self.stream,
            self.group,
            consumer,
            min_idle_ms,
            "0-0",
            count=count,
        )
        rows = response[1] if isinstance(response, (list, tuple)) and len(response) > 1 else []
        return [_message(message_id, fields) for message_id, fields in rows]

    async def ack(self, message_id: str) -> None:
        await self.redis.xack(self.stream, self.group, message_id)

    async def heartbeat(self, consumer: str, ttl_seconds: int) -> None:
        await self.redis.set(f"{self.stream}:heartbeat:{consumer}", "alive", ex=ttl_seconds)


@asynccontextmanager
async def redis_lock(
    redis: Redis,
    key: str,
    *,
    ttl_seconds: int,
) -> AsyncIterator[bool]:
    token = uuid.uuid4().hex
    acquired = bool(await redis.set(key, token, nx=True, ex=ttl_seconds))
    try:
        yield acquired
    finally:
        if acquired:
            release = redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )
            await cast(Awaitable[Any], release)


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _message(message_id: Any, fields: dict[Any, Any]) -> QueueMessage:
    raw_job_id = fields.get("job_id", fields.get(b"job_id"))
    return QueueMessage(message_id=_text(message_id), job_id=UUID(_text(raw_job_id)))


def _first_message(rows: Any) -> QueueMessage | None:
    if not rows:
        return None
    _stream, messages = rows[0]
    if not messages:
        return None
    return _message(*messages[0])
