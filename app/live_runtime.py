import asyncio
from collections import deque


class LiveEventQueue(asyncio.Queue):
    """Bounded per-user event queue with explicit lifecycle gating."""

    def __init__(self, maxsize: int = 100):
        super().__init__(maxsize=maxsize)
        self.ready = False
        self.closed = False
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque(maxlen=500)

    def mark_ready(self) -> None:
        self.ready = True

    def close(self) -> None:
        self.closed = True
        self.ready = False
        while not self.empty():
            try:
                self.get_nowait()
                self.task_done()
            except asyncio.QueueEmpty:
                break
        self._seen_ids.clear()
        self._seen_order.clear()

    async def put(self, item):
        if self.closed or not self.ready:
            return
        event_id = item.get("id") if isinstance(item, dict) else None
        if event_id:
            event_id = str(event_id)
            if event_id in self._seen_ids:
                return
            self._seen_ids.add(event_id)
            self._seen_order.append(event_id)
            if len(self._seen_order) == self._seen_order.maxlen:
                self._seen_ids = set(self._seen_order)
        if isinstance(item, dict) and item.get("event_type") == "like":
            username = item.get("username")
            for pending in self._queue:
                if isinstance(pending, dict) and pending.get("event_type") == "like" and pending.get("username") == username:
                    pending["count"] = int(pending.get("count", 1) or 1) + int(item.get("count", 1) or 1)
                    return
        if self.full():
            event_type = item.get("event_type") if isinstance(item, dict) else None
            if event_type == "like":
                return
            try:
                oldest = self.get_nowait()
                self.task_done()
                if isinstance(oldest, dict) and oldest.get("event_type") in {"comment", "gift", "follow"}:
                    try:
                        self.put_nowait(oldest)
                    except asyncio.QueueFull:
                        pass
            except asyncio.QueueEmpty:
                pass
        await super().put(item)


session_states: dict[int, str] = {}


def get_live_status(user_id: int, *, username: str | None = None) -> dict:
    return {"status": session_states.get(user_id, "stopped"), "tiktok_username": username}


def set_live_state(user_id: int, state: str) -> None:
    session_states[user_id] = state


def mark_live_ready(user_id: int, queues: dict) -> None:
    queue = queues.get(user_id)
    if queue is not None and not queue.closed:
        queue.mark_ready()
    set_live_state(user_id, "ready")
    print(f"[live] user_id={user_id} ready")


def mark_live_failed(user_id: int, queues: dict, reason: str | None = None) -> None:
    queue = queues.get(user_id)
    if queue is not None:
        queue.ready = False
    set_live_state(user_id, "failed")
    message = f" reason={reason}" if reason else ""
    print(f"[live] user_id={user_id} failed{message}")


def stop_runtime_session(user_id: int, queues: dict) -> None:
    queue = queues.get(user_id)
    if queue is not None:
        queue.close()
    set_live_state(user_id, "stopped")
