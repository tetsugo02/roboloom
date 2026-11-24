"""Taking dora events, shared by the node loops (`runtime.node`) and the viewer.

The loops keep only the newest sample per input, so a slow reader never holds back
the flow; `_events` collapses a buffered backlog into its samples plus one tick.
"""

from __future__ import annotations

from ..core.protocol import Envelope


def _send(node, output: str, msg: Envelope) -> None:
    node.send_output(output, msg.encode())


def _decode_event(event) -> tuple[str | None, Envelope | None]:
    if event is None:
        return None, None
    if event.get("type") == "INPUT_CLOSED" and event.get("id") == "report":
        return "report_closed", None
    if event.get("type") != "INPUT":
        return None, None
    return event["id"], None if event["id"] == "tick" else Envelope.decode(
        event["value"]
    )


def _event(node):
    return _decode_event(node.next(timeout=0.1))


def _events(node, take=None) -> list[tuple[str | None, Envelope | None]]:
    """Take the next event (waiting up to 0.1 s) plus any already buffered on `node`,
    collapsing a backlog of `tick`s into one after the incoming samples in the batch.
    `take` reads one event: `runtime.node` passes its own `_event`, so a taker patched
    there (tests) still drives the batch."""
    first = (_event if take is None else take)(node)
    if first == (None, None) or not hasattr(node, "drain"):
        return [first]
    batch = [first, *(_decode_event(e) for e in node.drain())]
    out: list[tuple[str | None, Envelope | None]] = []
    saw_tick = False
    for eid, msg in batch:
        if eid is None:
            continue
        if eid == "tick":
            saw_tick = True
        else:
            out.append((eid, msg))
    if saw_tick:
        out.append(("tick", None))
    return out or [(None, None)]


def _quit(event_id, msg) -> bool:
    return (
        event_id == "session" and msg is not None and msg.payload["command"] == "quit"
    )
