import asyncio
from collections import deque
from time import monotonic


class LiveEventQueue(asyncio.Queue):
    """Bounded per-user event queue with startup gating and deduplication."""

    def __init__(self, maxsize: int = 100):
        super().__init__(maxsize=maxsize)
        self.ready = False
        self.closed = False
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque(maxlen=500)
        self._started_at = monotonic()

    def mark_ready(self) -> None:
        self.ready = True
        print("[live-queue] READY: accepting new TikTok events")

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
                print(f"[live-queue] DROP duplicate id={event_id}")
                return
            self._seen_ids.add(event_id)
            self._seen_order.append(event_id)
            if len(self._seen_order) == self._seen_order.maxlen:
                self._seen_ids = set(self._seen_order)

        # Collapse bursts of likes from the same viewer into one pending event.
        if isinstance(item, dict) and item.get("event_type") == "like":
            username = item.get("username")
            for pending in self._queue:
                if (isinstance(pending, dict)
                        and pending.get("event_type") == "like"
                        and pending.get("username") == username):
                    pending["count"] = int(pending.get("count", 1) or 1) + int(item.get("count", 1) or 1)
                    return

        if self.full():
            event_type = item.get("event_type") if isinstance(item, dict) else None
            if event_type == "like":
                print("[live-queue] DROP like: queue full")
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
_session_tasks: dict[int, asyncio.Task] = {}


def get_live_status(user_id: int, *, username: str | None = None) -> dict:
    return {
        "status": session_states.get(user_id, "stopped"),
        "tiktok_username": username,
    }


def set_live_state(user_id: int, state: str) -> None:
    session_states[user_id] = state
    print(f"[live] user_id={user_id} state={state}")


def cancel_session_monitor(user_id: int) -> None:
    task = _session_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()


def start_session_monitor(user_id: int, queue: LiveEventQueue, clients: dict, username: str) -> None:
    cancel_session_monitor(user_id)
    set_live_state(user_id, "connecting")

    async def monitor():
        try:
            deadline = monotonic() + 10.0
            while monotonic() < deadline:
                client = clients.get(user_id)
                if client is None:
                    set_live_state(user_id, "failed")
                    return
                if getattr(client, "connected", False):
                    queue.mark_ready()
                    set_live_state(user_id, "ready")
                    break
                await asyncio.sleep(0.1)
            else:
                set_live_state(user_id, "failed")
                return

            while True:
                await asyncio.sleep(1.0)
                if user_id not in clients:
                    set_live_state(user_id, "failed")
                    return
                if not getattr(clients[user_id], "connected", False):
                    set_live_state(user_id, "failed")
                    return
        except asyncio.CancelledError:
            raise

    _session_tasks[user_id] = asyncio.create_task(monitor())


def stop_runtime_session(user_id: int, queues: dict) -> None:
    cancel_session_monitor(user_id)
    queue = queues.get(user_id)
    if queue is not None:
        queue.close()
    set_live_state(user_id, "stopped")
