import shutil
from copy import deepcopy
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
import yaml
from conftest import TEMPLATE, rakuda2_tree
from test_dynamics import INPUTS, URDF, physics, poses

from roboloom import tools
from roboloom.config import parse_experiment
from roboloom.dynamics.regressor import Fit, JointMap, Regressor, RegressorGravityModel
from roboloom.tools import Calibration, fit_gravity

RAKUDA_URDF = Path("src/roboloom/robots/rakuda2/model/assembly_2.urdf")


def toy_calibration(tmp_path, directions=(1, 1, -1)):
    (tmp_path / "toy.urdf").write_text(URDF)
    joints = [
        {
            "name": m.name,
            "motor_id": k + 1,
            "urdf": m.urdf,
            "zero": 2048,
            "direction": d,
        }
        for k, (m, d) in enumerate(zip(INPUTS, directions, strict=True))
    ]
    path = tmp_path / "cal.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "port": "/dev/null",
                "urdf": "toy.urdf",
                "confirmed": True,
                "joints": joints,
                "outputs": ["a", "b"],
            }
        )
    )
    samples = np.repeat(poses(16), 2, axis=0)
    currents = np.array([physics(q) for q in samples]) + np.random.default_rng(
        2
    ).normal(0, 0.5, (32, 2))
    np.savez(
        tmp_path / "data.npz",
        positions=samples,
        currents_mA=currents,
        pose=np.repeat(np.arange(16), 2),
        joints=np.array(["yaw", "a", "b"]),
        outputs=np.array(["a", "b"]),
    )
    return Calibration(path)


def test_fit_gravity_saves_a_loadable_model(tmp_path):
    cal = toy_calibration(tmp_path)
    report = fit_gravity(
        cal, tmp_path / "data.npz", tmp_path / "gravity.yaml", max_rms_mA=2.0
    )
    assert (
        "saved" in report and "warning" in report
    )  # the planar toy has a mirrored direction set
    model = RegressorGravityModel.load(tmp_path / "gravity.yaml")
    q = poses(1, seed=5)[0]
    assert np.allclose(model.effort_mA(q), physics(q), atol=1.0)


def test_fit_gravity_refuses_unconfirmed_wrong_or_noisy(tmp_path):
    cal = toy_calibration(tmp_path, directions=(1, -1, -1))
    with pytest.raises(SystemExit, match="fit much better"):
        fit_gravity(cal, tmp_path / "data.npz", tmp_path / "g.yaml", max_rms_mA=2.0)
    cal = toy_calibration(tmp_path)
    with pytest.raises(SystemExit, match="not saved"):
        fit_gravity(cal, tmp_path / "data.npz", tmp_path / "g.yaml", max_rms_mA=0.01)
    cal.data["confirmed"] = False
    with pytest.raises(SystemExit, match="confirmed"):
        fit_gravity(cal, tmp_path / "data.npz", tmp_path / "g.yaml", max_rms_mA=2.0)


class FakeDynamixel:
    """Registers of a commissioned-or-not bus for `commission`."""

    instances: ClassVar[list] = []

    def __init__(self, port, ids):
        self.ids = ids
        self.registers = {
            "operating_mode": [3] * len(ids),
            "current_limit": [910] * len(ids),
            "torque_enable": [0] * len(ids),
        }
        self.writes = []
        FakeDynamixel.instances.append(self)

    def current_units_mA(self):
        return [1.0] * len(self.ids)

    def read_register(self, name):
        return list(self.registers[name])

    def write_eeprom(self, name, indices, values):
        self.writes.append((name, indices, values))
        for i, v in zip(indices, values, strict=True):
            self.registers[name][i] = v

    def close(self):
        pass


def synthetic_models(tmp_path):
    """Zero-parameter gravity models on the real Rakuda URDF, for configuration tests."""
    shutil.copy(RAKUDA_URDF, tmp_path / "assembly_2.urdf")
    paths = {}
    for side, p in (("right", "r"), ("left", "l")):
        cal = yaml.safe_load(
            (TEMPLATE / f"calibration/leader_{side}.yaml").read_text()
        )
        maps = [JointMap(j["name"], j["urdf"], 2048, 1) for j in cal["joints"]]
        reg = Regressor(RAKUDA_URDF.read_text(), maps, cal["outputs"])
        theta = [[0.0] * (4 * len(reg.bodies[u]) + 1) for u in reg.output_urdf]
        model = RegressorGravityModel(
            RAKUDA_URDF.read_text(), maps, cal["outputs"], theta
        )
        paths[side] = tmp_path / f"gravity_{side}.yaml"
        model.save(
            paths[side],
            tmp_path / "assembly_2.urdf",
            Fit(theta, [0] * 6, [1.0] * 6, [0.0] * 6),
        )
    return paths


def gravity_tree(tmp_path):
    paths = synthetic_models(tmp_path)
    tree = rakuda2_tree("experiment_gravity")
    for group in tree["inputs"]["leader"]["control"]:
        if group["law"] == "gravity_comp":
            group["gravity_model"] = str(paths[group["group"].split("_")[0]])
            group["range"] = [[500, 3500]] * 6
    return tree


def test_gravity_leader_example_parses_and_runs_in_mock(tmp_path):
    tree = gravity_tree(tmp_path)
    cfg = parse_experiment(
        deepcopy(tree)
    )  # hardware checks: watchdog and current limits present
    assert cfg.inputs["leader"].actuated
    tree["experiment"]["mode"] = "mock"
    cfg = parse_experiment(tree)
    reader = cfg.inputs["leader"].open(True, cfg.dataset_fps)
    reader.start_trace(tmp_path / "leader_trace.npz")
    for _ in range(3):
        assert len(reader.read().value) == 17
    assert "r_arm_grip" in reader.status()["current_mA"]  # the trigger spring pushes
    reader.close()
    trace = np.load(tmp_path / "leader_trace.npz")
    assert trace["positions"].shape == (3, 17)
    grip = list(trace["joints"]).index("r_arm_grip")
    assert np.isfinite(trace["commanded_mA"][:, grip]).all()
    assert np.isnan(trace["commanded_mA"][:, 0]).all()  # torso is free


def test_commission_writes_only_differences_after_confirmation(tmp_path, monkeypatch):
    tree = gravity_tree(tmp_path)
    path = tmp_path / "exp.yaml"
    monkeypatch.setattr(
        tools, "load_experiment", lambda _: parse_experiment(deepcopy(tree))
    )
    monkeypatch.setattr("roboloom.drivers.dynamixel.DynamixelBus", FakeDynamixel)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert tools.commission(str(path), "leader") == "cancelled"
    assert FakeDynamixel.instances[-1].writes == []
    result = tools.commission(str(path), "leader", yes=True)
    bus = FakeDynamixel.instances[-1]
    modes = dict(
        bus.writes[0][1:]
        and [(i, v) for i, v in zip(bus.writes[0][1], bus.writes[0][2], strict=True)]
    )
    assert (
        "wrote" in result and len(modes) == 12 and set(modes.values()) == {0}
    )  # arm joints to current mode
    grips = [w for w in bus.writes if w[0] == "operating_mode" and w[2][0] == 5]
    assert grips and sorted(grips[0][1]) == [9, 16]
    FakeDynamixel.instances.clear()


class WatchdogMotor:
    """One current-mode motor whose watchdog fires after `period_ms` without traffic."""

    def __init__(self, stops: bool):
        self.stops, self.torque, self.goal, self.watchdog = stops, 0, 0.0, 0
        self.period_ms, self.silent_ms = 0.0, 0.0

    def tick(self, ms):
        self.silent_ms += ms
        if self.watchdog > 0 and self.torque and self.silent_ms > self.period_ms:
            self.watchdog = -1
            if self.stops:
                self.goal = 0.0

    def _talk(self):
        self.silent_ms = 0.0

    def read_register(self, name):
        self._talk()
        return {
            "operating_mode": [0],
            "torque_enable": [self.torque],
            "bus_watchdog": [self.watchdog],
            "hardware_error": [0],
        }[name]

    def write_goal_currents(self, indices, values):
        self._talk()
        if self.watchdog >= 0:
            self.goal = values[0]

    def read_goal_currents(self):
        self._talk()
        return [self.goal]

    def set_bus_watchdog(self, period_ms):
        self._talk()
        self.watchdog = round((period_ms or 0) / 20)
        self.period_ms = period_ms or 0.0

    def set_torque(self, indices, on):
        self._talk()
        self.torque = int(on)

    def read_state(self):
        from roboloom.drivers.base import JointState

        self._talk()
        return JointState([2048.0], [0.0], [self.goal])


@pytest.mark.parametrize("stops", [True, False])
def test_watchdog_trial_reads_what_the_motor_did(stops):
    motor = WatchdogMotor(stops)
    r = tools.watchdog_trial(motor, 30.0, 100, sleep=lambda s: motor.tick(s * 1000))
    assert r["current_before_mA"] == 30.0 and r["watchdog_before"] == 5
    assert r["watchdog_after"] == -1
    assert r["current_after_mA"] == (0.0 if stops else 30.0)
    assert r["goal_after_zero_write_mA"] == (0.0 if stops else 30.0)
    assert motor.torque == 0 and motor.watchdog == 0 and motor.goal == 0.0
