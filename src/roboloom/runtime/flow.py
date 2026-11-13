"""Render the dora dataflow from a validated configuration."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import yaml

from ..config import RobotConfig
from ..recording import ACTION, action_stream

STATUS_SUFFIX = "_status"  # session input ids; runtime.node reads the same suffix
STATE_PREFIX = "state_"  # a controller's input carrying one follower's state


def command_output(follower: str) -> str:
    """A controller's output carrying its commands for `follower`."""
    return f"command_{follower}"


def build_flow(cfg: RobotConfig) -> dict:
    script = str(Path(__file__).with_name("node.py").resolve())
    fps = cfg.dataset_fps

    def node(name, inputs, outputs, tick=None):
        if tick is not None:
            inputs = {**inputs, "tick": f"dora/timer/hz/{int(tick)}"}
        return {
            "id": name,
            # this interpreter, so nodes import the same roboloom without an activated venv
            "path": sys.executable,
            "args": f"{script} {name} {cfg.path}",
            "inputs": inputs,
            "outputs": outputs,
            "restart_policy": "never",
        }

    session = {"session": "session/control"}  # every node ends on `quit`
    # a source without a rate of its own runs at the fastest follower it drives (an
    # input: through its controllers), or else at the fastest follower of the robot (a
    # configuration without followers gives every source its own rate, see config)
    fastest = max((f.control_hz for f in cfg.followers.values()), default=fps)
    driven = {
        n: max(
            (
                f.control_hz
                for c in cfg.controllers.values()
                if c.source is s
                for f in c.followers.values()
            ),
            default=fastest,
        )
        for n, s in cfg.inputs.items()
    }

    def rate(name: str, source) -> float:
        return source.rate_hz(fps) or driven.get(name, fastest)

    def latest(output: str) -> dict:
        return {"source": output, "queue_size": 1, "queue_policy": "drop_oldest"}

    # force feedback: the controller that sends it to each input
    feedback = {
        c.source.name: name
        for name, c in cfg.controllers.items()
        if c.feedback is not None and c.source is not None
    }
    # tracking systems: one node each serves the inputs that hold its tracked objects
    readers = {
        name: getattr(source, "tracker_system", lambda: None)()
        for name, source in cfg.inputs.items()
    }
    nodes = [
        node(
            name,
            session,
            ["poses", "status"],
            tracker.rate_hz()
            or max(
                (rate(n, cfg.inputs[n]) for n, s in readers.items() if s == name),
                default=fastest,
            ),
        )
        for name, tracker in cfg.trackers.items()
    ]
    nodes += [
        node(
            name,
            {
                **session,
                **(
                    {"feedback": latest(f"{feedback[name]}/feedback")}
                    if name in feedback
                    else {}
                ),
                **(
                    {"tracker": latest(f"{readers[name]}/poses")}
                    if readers[name] is not None
                    else {}
                ),
            },
            ["sample", "status"],
            rate(name, source),
        )
        for name, source in cfg.inputs.items()
    ]

    for name, c in cfg.controllers.items():
        inputs: dict[str, object] = {
            **{f"{STATE_PREFIX}{f}": f"{f}/state" for f in c.followers},
            **session,
        }
        outputs = [*(command_output(f) for f in c.followers), "status"]
        if c.source is not None:
            inputs["intent"] = f"{c.source.name}/sample"
        # a policy reads the newest sample of what it observes, on its own timer
        inputs.update({f"observe_{n}": latest(f"{n}/sample") for n in c.observes()})
        if c.feedback is not None:
            inputs["estimate"] = latest(f"{c.feedback.estimator_name}/estimate")
            outputs.append("feedback")
        # a policy runs at its command rate (rate_hz * interpolation_multiplier)
        nodes.append(node(name, inputs, outputs, getattr(c, "command_hz", None)))
    # estimators run on each follower state they receive, so they need no timer
    nodes += [
        node(
            name,
            {"follower": latest(f"{e.follower}/state"), **session},
            ["estimate", "status"],
        )
        for name, e in cfg.estimators.items()
    ]
    nodes += [
        node(
            name,
            {
                "command": {
                    "source": f"{cfg.controller_for(name).name}/{command_output(name)}",
                    "queue_size": 1,
                    "queue_policy": "drop_oldest",
                },
                "session": "session/control",
            },
            ["state", ACTION, "status"],
            robot.control_hz,
        )
        for name, robot in cfg.followers.items()
    ]
    nodes += [
        node(name, session, ["sample", "status"], rate(name, sensor))
        for name, sensor in cfg.sensors.items()
    ]
    # Bounded recorder queues: while `save` encodes video the recorder does not read, and dora
    # hands a node all queued events in one reply (64 MB limit). Keep about `queue_s` per stream.
    queue_s = float(cfg.recorder.get("queue_s", 0.5))

    def bounded(output: str, rate_hz: float) -> dict:
        return {
            "source": output,
            "queue_size": max(2, math.ceil(rate_hz * queue_s)),
            "queue_policy": "drop_oldest",
        }

    rates = {
        **{n: rate(n, s) for n, s in {**cfg.inputs, **cfg.sensors}.items()},
        **{n: r.control_hz for n, r in cfg.followers.items()},
        **{n: cfg.followers[e.follower].control_hz for n, e in cfg.estimators.items()},
    }
    published = {
        **{n: "state" for n in cfg.followers},
        **{n: "estimate" for n in cfg.estimators},
    }
    recorded = {
        name: bounded(f"{name}/{published.get(name, 'sample')}", rates[name])
        for name in cfg.sources
    }
    for name, follower in cfg.followers.items():
        recorded[action_stream(name)] = bounded(f"{name}/{ACTION}", follower.control_hz)
    nodes.append(node("recorder", {**recorded, **session}, ["report", "status"]))
    statuses = {
        f"{name}{STATUS_SUFFIX}": {
            "source": f"{name}/status",
            "queue_size": 2,
            "queue_policy": "drop_oldest",
        }
        for name in [n["id"] for n in nodes]
    }
    nodes.append(
        node("session", {"report": "recorder/report", **statuses}, ["control"])
    )
    return {"nodes": nodes}


def write_flow(cfg: RobotConfig, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(yaml.safe_dump(build_flow(cfg), sort_keys=False))
    return target
