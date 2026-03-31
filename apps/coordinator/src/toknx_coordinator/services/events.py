import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class EventMessage:
    event: str
    payload: dict
    created_at: str


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[EventMessage]] = set()

    async def publish(self, event: str, payload: dict) -> None:
        message = EventMessage(
            event=event,
            payload=payload,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        for subscriber in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                subscriber.put_nowait(message)

    def subscribe(self) -> asyncio.Queue[EventMessage]:
        queue: asyncio.Queue[EventMessage] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[EventMessage]) -> None:
        self._subscribers.discard(queue)

