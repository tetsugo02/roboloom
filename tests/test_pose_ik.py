"""The pose_ik controller: relative clutched mapping, refusals, and the mock teleoperation."""

from __future__ import annotations

import copy
import time

import numpy as np
import pytest

pytest.importorskip("pinocchio")

from roboloom.config import load_config
from roboloom.controllers.base import FollowerView
from roboloom.core.protocol import Publisher
from roboloom.kinematics.spec import pose_to, pose_xyz_rpy

CONFIG = ".roboloom/piper-mock/config.yaml"
READY = [0.0, 1.2, -0.9, 0.0, 0.3, 0.0]  # poses/left/ready.yaml


class Rig:
    """The left controller with a pretend arm that takes every command at once."""

    def __init__(self, **overrides):
        cfg = load_config(CONFIG)
        controller = cfg.controllers["left_ik"]
        if overrides:
            from roboloom.controllers.pose_ik import PoseIkController

            raw = copy.deepcopy(controller.cfg) | overrides
            controller = PoseIkController(
                "left_ik", raw, cfg.inputs["left_sense"], controller.followers
            )
        self.c, self.source = controller, cfg.inputs["left_sense"]
        self.publisher = Publisher("left_sense")
        self.arm, self.grip = list(READY), [0.2]
        self.mode = "HOLD"

    def send(
        self,
        pose=None,
        *,
        engaged=True,
        tracking=True,
        gripper=0.9,
        boot: str | None = None,
    ) -> dict:
        position, quaternion = pose_to(np.eye(4) if pose is None else pose)
        value = [*position, *quaternion, gripper, float(tracking), float(engaged)]
        sample = type("S", (), {"value": np.asarray(value), "capture_ns": 0})()
        msg = self.publisher.make(
            "pose_intent", self.source.encode(sample), time.monotonic_ns()
        )
        if boot is not None:
            msg = type(msg)(**{**msg.__dict__, "boot_id": boot})
        now = time.monotonic_ns()
        # as if the last command went out 50 ms ago: room for a speed-limited step
        self.c.last_ns = {k: v - 50_000_000 for k, v in self.c.last_ns.items()}
        views = {
            "left": FollowerView(self.arm, self.arm, None, self.mode, now),
            "left_gripper": FollowerView(self.grip, self.grip, None, self.mode, now),
        }
        out = self.c.update(msg, views, now)
        if "left" in out:
            self.arm = list(out["left"].payload["positions"])
        if "left_gripper" in out:
            self.grip = list(out["left_gripper"].payload["positions"])
        return out


def tool(arm: Rig) -> np.ndarray:
    return arm.c.model.fk(arm.arm)


def test_engaging_anchors_and_moves_the_tool_by_the_hand_motion():
    rig = Rig()
    hand = pose_xyz_rpy([1.0, 2.0, 0.5], [0.3, -0.2, 1.0])  # anywhere in the world
    assert rig.send(hand, engaged=False) == {} and rig.c.state == "ready"
    start = tool(rig)
    out = rig.send(hand)  # engaging: no motion yet
    assert set(out) == {"left", "left_gripper"} and rig.c.state == "following"
    assert np.allclose(tool(rig), start, atol=1e-3)
    step = pose_xyz_rpy([0.0, 0.0, 0.01], [0, 0, 0])  # 1 cm along the hand's own z
    for _ in range(20):  # the speed limit takes a few steps
        rig.send(hand @ step)
    assert np.allclose(tool(rig), start @ step, atol=2e-3)
    assert rig.grip == [pytest.approx(0.9, abs=1e-6)]


def test_the_gripper_follows_the_jaws_within_its_range():
    rig = Rig(gripper_map={"scale": 2.0, "offset": 0.0})
    rig.send(engaged=False)
    for _ in range(30):
        rig.send(gripper=1.5)
    assert rig.grip == [pytest.approx(1.6)]  # 3.0 clipped to the gripper's limit


def test_targets_outside_the_workspace_or_reach_are_not_sent():
    rig = Rig()
    rig.send(engaged=False)
    rig.send()
    held = list(rig.arm)
    assert rig.send(pose_xyz_rpy([0.0, 0.0, -0.4], [0, 0, 0])) == {}
    assert rig.c.state in ("out_of_workspace", "input_jump")
    assert rig.arm == held
    rig = Rig(max_input_jump={"position_m": 5.0, "rotation_rad": 5.0})
    rig.send(engaged=False)
    rig.send()
    assert rig.send(pose_xyz_rpy([0.0, 0.0, -0.4], [0, 0, 0])) == {}
    assert rig.c.state == "out_of_workspace"
    assert rig.send(pose_xyz_rpy([0.0, 0.0, 0.0], [0, 3.0, 0])) == {}
    assert rig.c.state == "unreachable"
    assert rig.send() != {}  # back where it was: following again, still engaged


def test_a_jump_a_lost_pose_a_fault_or_a_move_home_needs_a_new_engagement():
    for interrupt in ("jump", "tracking", "reset", "homing", "boot"):
        rig = Rig()
        rig.send(engaged=False)
        rig.send()
        if interrupt == "jump":
            assert rig.send(pose_xyz_rpy([0.1, 0, 0], [0, 0, 0])) == {}
            assert rig.c.state == "input_jump"
        elif interrupt == "tracking":
            assert rig.send(tracking=False) == {}
            assert rig.c.state == "tracking_lost"
        elif interrupt == "reset":
            rig.c.reset()
        elif interrupt == "homing":
            rig.mode = "HOMING"
            assert rig.send() == {} and rig.c.state == "homing"
            rig.mode = "HOLD"
        else:
            assert rig.send(boot="another-boot") == {}
        assert rig.send() == {}, interrupt  # still engaged on the device: not enough
        rig.send(engaged=False)
        assert rig.send() != {}, interrupt  # engaged again on purpose


def test_the_configuration_is_checked():
    from roboloom.controllers.pose_ik import PoseIkController

    cfg = load_config(CONFIG)
    base = cfg.controllers["left_ik"]
    sense, followers = cfg.inputs["left_sense"], base.followers
    for change, match in (
        ({"arm": "left_gripper", "gripper": "left"}, "no kinematic model"),
        ({"gripper": None}, "exactly its followers"),
        ({"workspace": {"min": [0, 0, 0], "max": [0, 1, 1]}}, "below max"),
        ({"tool_offset": {"xyz": "SET_TOOL", "rpy": [0, 0, 0]}}, "3 numbers"),
        ({"ik": {"steps": 3}}, "unknown keys"),
        ({"max_speed": {"left": 1.0}}, "one value per follower"),
        ({"home": {"right": {}}}, "mapping of its followers"),
    ):
        raw = copy.deepcopy(base.cfg) | change
        with pytest.raises(ValueError, match=match):
            PoseIkController("left_ik", raw, sense, followers)
    with pytest.raises(TypeError, match="pose input"):
        PoseIkController("left_ik", base.cfg, cfg.followers["left"], followers)  # type: ignore[arg-type]


def test_two_senses_teleoperate_the_mock_and_the_dataset_records_them(tmp_path):
    import json
    import shutil

    from roboloom.runtime.session import Session

    project = tmp_path / ".roboloom" / "piper-mock"
    shutil.copytree(
        ".roboloom/piper-mock",
        project,
        ignore=shutil.ignore_patterns("datasets", "__pycache__"),
    )
    with Session.launch(project / "config.yaml", log_dir=tmp_path / "logs") as s:
        assert s.held == []
        s.home(timeout=30)
        s.wait_ready(30)
        deadline = time.monotonic() + 15
        while s.status()["left_ik"]["fields"].get("state") != "following":
            assert time.monotonic() < deadline, s.status()["left_ik"]
            time.sleep(0.1)
        result = s.record("follow", 2.0)
        status = s.status()
    assert result.saved, result
    assert result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert status["right_ik"]["fields"]["state"] == "following"
    info = json.loads((project / "datasets/piper-mock/meta/info.json").read_text())
    features = info["features"]
    assert features["action"]["shape"] == [14]
    assert features["observation.left_sense"]["shape"] == [9]
    assert features["observation.right_sense"]["names"][7] == "gripper"


def test_the_screen_says_what_the_operator_does():
    from roboloom.ui.render import RENDERERS

    _, detail = RENDERERS["controller"]({"state": "ready", "engaged": False})
    assert "double-click" in detail.plain
    _, detail = RENDERERS["controller"](
        {
            "state": "unreachable",
            "engaged": True,
            "position_error_mm": 12.0,
            "rotation_error_deg": 1.5,
        }
    )
    assert "cannot reach" in detail.plain and "12.0 mm" in detail.plain
    _, detail = RENDERERS["controller"]({"state": "ready"})  # a policy: no pose advice
    assert "double-click" not in detail.plain


def test_a_gap_in_input_delivery_needs_a_new_engagement():
    rig = Rig()
    rig.send(engaged=False)
    assert rig.send() != {}
    rig.c.last_input_ns -= 1_000_000_000  # the input went silent for a second
    assert rig.send() == {} and rig.c.state == "input_stale"  # fresh, but after a gap
    assert rig.send() == {}  # still engaged on the device: not enough
    rig.send(engaged=False)
    assert rig.send() != {}


def test_held_time_gives_no_extra_speed_budget():
    rig = Rig(max_input_jump={"position_m": 5.0, "rotation_rad": 5.0})
    rig.send(engaged=False)
    rig.send()
    before = time.monotonic_ns()
    assert rig.send(pose_xyz_rpy([0.0, 0.0, 0.0], [0, 3.0, 0])) == {}
    assert rig.c.state == "unreachable"
    # withholding moves the limiter's clock along: the held time is not saved up
    assert all(v >= before for v in rig.c.last_ns.values())
    # and one command never spends more than one input timeout of motion
    rig.c.last_ns = {k: v - 2_000_000_000 for k, v in rig.c.last_ns.items()}
    held = list(rig.arm)
    rig.send(pose_xyz_rpy([0.0, 0.0, 0.03], [0, 0, 0]))
    limit = rig.c.max_speed["left"] * rig.c.input_timeout_ms / 1000
    assert max(abs(a - b) for a, b in zip(rig.arm, held, strict=True)) <= limit + 1e-9
