"""Rakuda2 option `pika`: a Pika Sense per arm through IK, on parts of the one follower
(mock only; nothing here says the joint map or the gripper map is right on a robot)."""

from __future__ import annotations

import time

import numpy as np
import pytest
from conftest import mock_project

pytest.importorskip("pinocchio")

from roboloom.config import load_config
from roboloom.controllers.base import FollowerView
from roboloom.core.protocol import Publisher
from roboloom.errors import ConfigError
from roboloom.kinematics.spec import pose_to, pose_xyz_rpy

FILLED = {
    "SET_RIGHT_SENSE_PORT": "/dev/serial/by-path/mock-sense-right",
    "SET_LEFT_SENSE_PORT": "/dev/serial/by-path/mock-sense-left",
    "SET_RIGHT_TRACKER_SERIAL": "LHR-MOCK0002",
    "SET_LEFT_TRACKER_SERIAL": "LHR-MOCK0001",
    "SET_RIGHT_GRIPPER_COUNTS_PER_RAD": "800",
    "SET_LEFT_GRIPPER_COUNTS_PER_RAD": "800",
    "SET_RIGHT_GRIPPER_CLOSED_COUNT": "1000",
    "SET_LEFT_GRIPPER_CLOSED_COUNT": "1000",
}
# a bent right arm (counts): the straight arm at 2048 is singular for the IK
BENT = {3: 2248.0, 4: 1748.0, 5: 2298.0, 6: 2448.0, 7: 2148.0, 8: 1898.0}


def _project(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    for path in (project / "nodes").glob("*.yaml"):
        text = path.read_text()
        for old, new in FILLED.items():
            text = text.replace(old, new)
        path.write_text(text)
    return project / "config.yaml"


class Rig:
    """The parts controller with a pretend follower that takes every command at once."""

    def __init__(self, tmp_path):
        self.cfg = load_config(_project(tmp_path), options=["pika"])
        self.c = self.cfg.controllers["controller"]
        self.pose = [2048.0] * 17
        for i, value in BENT.items():
            self.pose[i] = value
        self.publishers = {n: Publisher(n) for n in ("right_sense", "left_sense")}

    def send(self, hand: str, pose, *, engaged=True, gripper=0.5) -> dict:
        position, quaternion = pose_to(pose)
        value = [*position, *quaternion, gripper, 1.0, float(engaged)]
        sample = type("S", (), {"value": np.asarray(value), "capture_ns": 0})()
        msg = self.publishers[hand].make(
            "pose_intent", self.cfg.inputs[hand].encode(sample), time.monotonic_ns()
        )
        now = time.monotonic_ns()
        for inner in self.c.inner.values():  # room for a speed-limited step
            inner.last_ns = {k: v - 50_000_000 for k, v in inner.last_ns.items()}
        view = FollowerView(list(self.pose), list(self.pose), None, "HOLD", now)
        out = self.c.update_from(hand, msg, {"follower": view}, now)
        if out:
            self.pose = list(out["follower"].payload["positions"])
        return out


def test_the_option_wires_two_senses_to_the_arms(tmp_path):
    cfg = load_config(_project(tmp_path), options=["pika"])
    assert (
        set(cfg.inputs) == {"right_sense", "left_sense"}
        and "lighthouse" in cfg.trackers
    )
    controller = cfg.controllers["controller"]
    assert set(controller.inner) == {"pika_right", "pika_left"}
    assert controller.intent_inputs() == ["right_sense", "left_sense"]
    assert cfg.repo_id.endswith("-pika")
    right = controller.inner["pika_right"]
    assert right.spec.names == cfg.followers["follower"].parts()["right_arm"]
    # leader teleoperation is unchanged by the files the option adds
    plain = load_config(_project(tmp_path / "plain"))
    assert set(plain.inputs) == {"leader"} and not plain.trackers


def test_a_hand_moves_its_arm_and_gripper_and_nothing_else(tmp_path):
    rig = Rig(tmp_path)
    start = list(rig.pose)
    hand = pose_xyz_rpy([1.0, 2.0, 0.5], [0.3, -0.2, 1.0])
    assert rig.send("right_sense", hand, engaged=False) == {}
    out = rig.send("right_sense", hand)  # engaging: the arm stays, the gripper follows
    assert set(out) == {"follower"} and len(rig.pose) == 17
    assert np.allclose(rig.pose[3:9], start[3:9], atol=2.0)
    right = rig.c.inner["pika_right"]
    tool = right.model.fk(right.spec.to_model(rig.pose[3:9]))
    # 1 cm along the hand's own x (a direction this arm can follow from this pose; the
    # IK of the shipped URDF is poorly conditioned along others, see the docs)
    step = pose_xyz_rpy([0.01, 0.0, 0.0], [0, 0, 0])
    for _ in range(30):
        rig.send("right_sense", hand @ step)
    assert rig.c.status()["parts"]["pika_right"] == "following"
    moved = right.model.fk(right.spec.to_model(rig.pose[3:9]))
    assert np.allclose(
        moved[:3, 3], (tool @ step)[:3, 3], atol=6e-3
    )  # ik tolerance 5 mm
    assert np.linalg.norm(moved[:3, 3] - tool[:3, 3]) > 4e-3
    assert not np.allclose(rig.pose[3:9], start[3:9], atol=2.0)  # counts changed
    # the jaw angle becomes gripper counts: 800 * 0.5 + 1000
    assert rig.pose[9] == pytest.approx(1400.0, abs=1.0)
    # torso, head and the whole left side stay where the follower held them
    assert rig.pose[:3] == start[:3] and rig.pose[10:] == start[10:]
    # every target is inside the follower's limits (counts)
    limits = rig.cfg.followers["follower"].limits
    assert all(
        lim["min"] <= x <= lim["max"] for x, lim in zip(rig.pose, limits, strict=True)
    )


def test_hardware_refuses_an_unconfirmed_joint_map(tmp_path):
    path = _project(tmp_path)
    with pytest.raises(ConfigError, match="not confirmed"):
        load_config(path, options=["pika"], mock=False)
    for side in ("right", "left"):
        file = path.parent / "calibration" / f"follower_{side}.yaml"
        file.write_text(file.read_text().replace("confirmed: false", "confirmed: true"))
    cfg = load_config(path, options=["pika"], mock=False)
    assert cfg.controllers["controller"].inner["pika_right"].spec.confirmed


def test_the_option_runs_in_the_mock_dataflow(tmp_path):
    from roboloom.runtime.session import Session

    with Session.launch(
        _project(tmp_path), options=["pika"], log_dir=tmp_path / "logs"
    ) as s:
        s.wait_ready(60)
        result = s.record("pick", 3.0)
        status = s.status()
    assert result.saved, result
    fields = status["controller"]["fields"]
    assert set(fields["parts"]) == {"pika_right", "pika_left"}, fields
    assert status["right_sense"]["fields"], status
