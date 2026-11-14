"""Several inputs on one follower, each driving its own joints (`type: parts`).

A follower with many joints (a two-armed robot on one bus) can be operated by several
devices: one hand-held device per arm through inverse kinematics, a leader for one arm
only, and so on. The follower names its parts (`Follower.parts()`: the model's own and
the follower YAML's `parts:`); this controller owns one inner controller per input, each
written for a part as if the part were a follower of its own:

    type: parts
    followers: [follower]
    command_deadline_ms: 100
    parts: [right_hand.yaml, left_hand.yaml]   # controller YAML files next to this one

    # right_hand.yaml: any controller type, its followers are parts of the follower
    type: pose_ik
    input: right_sense
    followers: [follower.right_arm, follower.right_gripper]
    ...

The follower still gets one command with all its joints, from one controller, so its
safety checks, the recorded `action` and the dataset stay as with any other controller.
Each inner controller steps from what the follower holds for its own joints. A part's
target is repeated in the commands the other inputs cause only while it is valid: for
its controller's `command_deadline_ms` after it was commanded, and not after that
controller has withheld a command (input lost, not engaged, unreachable). After that,
and for joints no part drives, the command carries what the follower holds, so a part
whose input stopped does not keep moving toward an old target.

Inner controllers have no `home` and no `feedback` of their own yet.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import ClassVar

from ..core.protocol import Envelope
from ..inputs.base import InputDevice
from ..robots.base import Follower
from .base import Controller, FollowerView


class PartsController(Controller):
    uses_input: ClassVar[bool] = False  # its inner controllers follow the inputs
    max_followers: ClassVar[int | None] = 1
    keys = (*Controller.keys, "parts", "input_timeout_ms")

    def __init__(
        self,
        name: str,
        cfg: dict,
        source: InputDevice | None,
        followers: Mapping[str, Follower],
    ):
        super().__init__(name, cfg, source, followers)
        self.inner: dict[str, Controller] = {}  # set by `bind_parts`
        self.index: dict[str, list[int]] = {}  # part name -> the follower's joints
        # part name -> (the targets last commanded, when): valid for a deadline
        self.commanded: dict[str, tuple[list[float], int]] = {}

    def bind_parts(self, controllers: Mapping[str, Controller]) -> None:
        """The inner controllers; together they drive every joint at most once."""
        follower = self.follower
        owner: dict[str, str] = {}
        for name, c in controllers.items():
            if c.homes or c.feedback is not None or "feedback" in c.cfg:
                raise ValueError(
                    f"{self.name}.parts: {name} cannot have home or feedback (set home "
                    "on the parts controller)"
                )
            for part in c.followers.values():
                if getattr(part, "parent", None) is not follower:
                    raise ValueError(
                        f"{self.name}.parts: {name} drives {part.name!r}, which is not "
                        f"a part of {follower.name!r} ({', '.join(follower.parts())})"
                    )
                for joint in part.joint_names:
                    if joint in owner:
                        raise ValueError(
                            f"{self.name}.parts: {joint} is driven by both "
                            f"{owner[joint]} and {name}"
                        )
                    owner[joint] = name
                self.index[part.name] = [
                    follower.joint_names.index(j) for j in part.joint_names
                ]
        if not controllers:
            raise ValueError(f"{self.name}.parts: name at least one controller file")
        self.inner = dict(controllers)

    def nested(self) -> list[Controller]:
        return list(self.inner.values())

    def intent_inputs(self) -> list[str]:
        return list(
            dict.fromkeys(c.source.name for c in self.inner.values() if c.source)
        )

    def _part_view(self, view: FollowerView, part: str) -> FollowerView:
        index = self.index[part]

        def pick(values: list[float] | None) -> list[float] | None:
            return None if values is None else [values[i] for i in index]

        return FollowerView(
            [view.positions[i] for i in index],
            pick(view.target),
            pick(view.velocities),
            view.mode,
            view.t_ns,
        )

    def update_from(
        self,
        input_name: str,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        follower = self.follower.name
        view = views[follower]
        now = time.monotonic_ns() if now_ns is None else now_ns
        moved = False
        for c in self.inner.values():
            if c.source is None or c.source.name != input_name:
                continue
            parts = {p: self._part_view(view, p) for p in c.followers}
            commands = c.update(intent, parts, now_ns)
            for part in c.followers:
                if part in commands:
                    positions = [float(x) for x in commands[part].payload["positions"]]
                    self.commanded[part] = (positions, now)
                    moved = True
                else:  # withheld: the part's joints go back to what the follower holds
                    self.commanded.pop(part, None)
        if not moved:
            return {}
        # the other parts: their target while it is valid, else what the follower holds
        # (never an old request the follower may not have reached)
        merged = [float(x) for x in view.target or view.positions]
        for c in self.inner.values():
            for part in c.followers:
                if part not in self.commanded:
                    continue
                positions, at = self.commanded[part]
                if now - at > c.deadline_ms * 1e6:
                    del self.commanded[part]
                    continue
                for i, value in zip(self.index[part], positions, strict=True):
                    merged[i] = value
        return {follower: self.command(follower, merged, now)}

    def update(
        self,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        return self.update_from(intent.source_id, intent, views, now_ns)

    def reset(self) -> None:
        for c in self.inner.values():
            c.reset()
        self.commanded.clear()

    def status(self) -> dict:
        states = {name: c.status() for name, c in self.inner.items()}
        each = {name: str(s.get("state", "")) for name, s in states.items()}
        following = [s for s in each.values() if s == "following"]
        return {
            # the operator screen reads `following` as "commanding"
            "state": "following"
            if following
            else ", ".join(f"{name}: {state}" for name, state in each.items()),
            "parts": each,
        }
