import shutil
from copy import deepcopy
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
import yaml
from test_dynamics import INPUTS, URDF, physics, poses

from roboloom import tools
from roboloom.config import parse_experiment, read_experiment
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
            Path(f"examples/rakuda2/calibration/leader_{side}.yaml").read_text()
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
    tree = read_experiment("examples/rakuda2/experiment_gravity.yaml")
    tree["inputs"]["leader"]["port"] = "/dev/serial/by-id/leader"
    tree["robots"]["robot"]["port"] = "/dev/serial/by-id/follower"
    for limit in tree["robots"]["robot"]["limits"]:
        limit["min"], limit["max"] = 1000, 3000
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
    assert len(reader.read().value) == 17
    reader.close()


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
