import shutil
import time
from copy import deepcopy

import pytest

from roboloom.config import parse_experiment, read_experiment
from roboloom.core.protocol import Publisher
from roboloom.estimators.base import Estimator
from roboloom.runtime.flow import build_flow

PATH = "examples/mock/experiment_bilateral.yaml"
ARM = [
    "r_arm_sh_pitch1",
    "r_arm_sh_roll",
    "r_arm_sh_pitch2",
    "r_arm_el_yaw",
    "r_arm_wr_roll",
    "r_arm_wr_yaw",
]


def estimate(cfg, residual, *, valid=True, contact=True, joints=None, unit="mA"):
    est = cfg.estimators["effort"]
    payload = {
        "robot": "robot",
        "joints": list(joints or est.joint_names),
        "unit": unit,
        "residual": residual,
        "contact": contact,
        "valid": valid,
        "robot_t_ns": 1,
    }
    return Publisher("effort").make(Estimator.kind, payload)


def test_feedback_edges_are_derived_from_node_references():
    nodes = {
        n["id"]: n for n in build_flow(parse_experiment(read_experiment(PATH)))["nodes"]
    }
    latest = {"queue_size": 1, "queue_policy": "drop_oldest"}
    assert nodes["effort"]["inputs"]["robot"] == {"source": "robot/state", **latest}
    assert nodes["effort"]["outputs"] == ["estimate", "status"]
    assert "tick" not in nodes["effort"]["inputs"]
    assert nodes["controller"]["inputs"]["estimate"] == {
        "source": "effort/estimate",
        **latest,
    }
    assert "feedback" in nodes["controller"]["outputs"]
    assert nodes["leader"]["inputs"]["feedback"] == {
        "source": "controller/feedback",
        **latest,
    }
    assert "effort_status" in nodes["session"]["inputs"]


def test_experiment_without_feedback_has_no_feedback_edges():
    nodes = build_flow(
        parse_experiment(read_experiment("examples/mock/experiment.yaml"))
    )
    for n in nodes["nodes"]:
        assert "feedback" not in n["inputs"] and "estimate" not in n["inputs"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda t: t["controllers"]["controller"]["feedback"].update(
                estimator="missing"
            ),
            "no estimator 'missing'",
        ),
        (
            lambda t: t["estimators"]["effort"].update(robot="other"),
            "must reference a configured robot",
        ),
        (
            lambda t: t["controllers"]["controller"]["feedback"].update(unit="mA/Nm"),
            "unit must be 'mA/mA'",
        ),
        (
            lambda t: t["inputs"]["leader"]["control"][1].pop("feedback"),
            "take no feedback",
        ),
        (
            lambda t: t["estimators"]["effort"].update(joints=["r_arm_el_yaw", "tail"]),
            "not joints of robot",
        ),
        (
            lambda t: t["estimators"]["effort"].update(joints=["l_arm_el_yaw"]),
            "does not estimate",
        ),
        (
            lambda t: t["controllers"]["controller"]["feedback"]["gain"].update(
                r_arm_el_yaw=-1
            ),
            "must be a finite number >= 0",
        ),
        (
            lambda t: t["inputs"]["leader"]["control"][0].update(feedback={}),
            "feedback needs a current-mode law",
        ),
        (
            lambda t: t["estimators"]["effort"].update(contact_on=1, contact_off=2),
            "contact_off <= contact_on",
        ),
    ],
)
def test_feedback_configuration_errors_fail_at_load(change, message):
    tree = deepcopy(read_experiment(PATH))
    change(tree)
    with pytest.raises(ValueError, match=message):
        parse_experiment(tree)


def test_feedback_maps_residuals_to_leader_joints_with_sign_and_gain():
    tree = read_experiment(PATH)
    for j in tree["controllers"]["controller"]["joints"]:
        if j["follower"] == "l_arm_el_yaw":
            j["sign"] = -1
    cfg = parse_experiment(tree)
    feedback = cfg.controllers["controller"].feedback
    est = cfg.estimators["effort"]
    residual = [0.0] * len(est.joint_names)
    residual[est.joint_names.index("r_arm_el_yaw")] = 20.0
    residual[est.joint_names.index("l_arm_el_yaw")] = 20.0
    now = time.monotonic_ns()
    msg = feedback.make(estimate(cfg, residual), "ACTIVE", True, now)
    assert msg is not None and msg.kind == "feedback"
    p = msg.payload
    assert p["joints"] == ["r_arm_el_yaw", "l_arm_el_yaw"]
    assert p["effort"] == pytest.approx([-2.0, 2.0])  # -k * sign * residual
    assert p["unit"] == "mA" and p["gate"] is True
    assert p["deadline_ns"] == now + 100_000_000


@pytest.mark.parametrize(
    ("mode", "following", "valid", "contact"),
    [
        ("HOLD", True, True, True),
        ("ACTIVE", False, True, True),
        ("ACTIVE", True, False, True),
        ("ACTIVE", True, True, False),
    ],
)
def test_feedback_gate_closes_unless_following_an_active_robot_in_contact(
    mode, following, valid, contact
):
    cfg = parse_experiment(read_experiment(PATH))
    feedback = cfg.controllers["controller"].feedback
    zeros = [0.0] * len(cfg.estimators["effort"].joint_names)
    msg = feedback.make(
        estimate(cfg, zeros, valid=valid, contact=contact), mode, following
    )
    assert msg is not None and msg.payload["gate"] is False


def test_feedback_refuses_an_estimate_that_does_not_match():
    cfg = parse_experiment(read_experiment(PATH))
    controller = cfg.controllers["controller"]
    zeros = [0.0] * len(cfg.estimators["effort"].joint_names)
    assert (
        controller.feedback.make(estimate(cfg, zeros, unit="Nm"), "ACTIVE", True)
        is None
    )
    assert "does not match" in controller.status()["feedback_error"]
    assert controller.status()["feedback_gate"] is False


class Fixed(Estimator):
    def __init__(self, name, cfg):
        super().__init__(name, cfg)
        self.value: list[float] | None = None

    def residual(self, state):
        return self.value


def test_estimator_smooths_and_detects_contact_with_hysteresis():
    est = Fixed(
        "e",
        {
            "robot": "robot",
            "joints": ["a", "b"],
            "smoothing_alpha": 0.5,
            "contact_on": 10,
            "contact_off": 4,
        },
    )
    est.value = [8.0, 4.0]
    first = est.update({})
    assert first.valid and first.residual == [8.0, 4.0] and first.contact  # 12 >= 10
    est.value = [0.0, 0.0]
    assert est.update({}).residual == [4.0, 2.0]  # 6 >= off: still in contact
    assert est.update({}).contact is False  # 3 < 4
    est.value = [6.0, 0.0]
    assert est.update({}).contact is False  # 4.5 < on
    est.value = None
    lost = est.update({})
    assert not lost.valid and not lost.contact and lost.residual == [0.0, 0.0]


def test_no_estimator_is_never_valid():
    cfg = parse_experiment(read_experiment(PATH))
    est = cfg.estimators["effort"]
    assert est.unit == "mA"
    out = est.update({"positions": [2048.0] * 17, "currents_mA": [0.0] * 17})
    assert not out.valid and not out.contact


def test_leader_takes_matching_feedback_and_drops_the_rest():
    cfg = parse_experiment(read_experiment(PATH))
    reader = cfg.inputs["leader"].open(True, cfg.dataset_fps)
    try:
        controller = cfg.controllers["controller"]
        zeros = [0.0] * len(cfg.estimators["effort"].joint_names)
        good = controller.feedback.make(
            estimate(cfg, zeros, contact=True), "ACTIVE", True
        )
        reader.on_feedback(good)
        device = reader.device
        index = device.joint_names.index("r_arm_el_yaw")
        assert set(device.feedback.effort_mA) == {
            index,
            device.joint_names.index("l_arm_el_yaw"),
        }
        assert device.feedback.gate is True
        assert reader.status()["feedback"] == {"gate": True, "received": 1}

        wrong_unit = Publisher("controller").make(
            "feedback",
            {**good.payload, "unit": "Nm", "gate": False},
        )
        reader.on_feedback(wrong_unit)
        assert "unit" in reader.status()["feedback_rejected"]
        assert device.feedback.gate is True  # the dropped message changed nothing

        unknown = Publisher("controller").make(
            "feedback", {**good.payload, "joints": ["torso_yaw", "r_arm_el_yaw"]}
        )
        reader.on_feedback(unknown)
        assert "torso_yaw" in reader.status()["feedback_rejected"]
        assert reader.status()["feedback"]["received"] == 1
    finally:
        reader.close()


def test_estimator_needs_a_robot_that_reports_effort():
    tree = read_experiment(PATH)
    cfg = parse_experiment(tree)
    robot = cfg.robots["robot"]
    est = Fixed("e", {"robot": "robot", "joints": ARM})
    type(robot).effort_signal, saved = None, type(robot).effort_signal
    try:
        with pytest.raises(ValueError, match="reports no effort"):
            est.bind(robot)
    finally:
        type(robot).effort_signal = saved


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_feedback_path_runs_end_to_end_in_mock(tmp_path):
    from roboloom.runtime.session import Session

    root = tmp_path / "mock"
    shutil.copytree("examples/mock", root)
    path = root / "experiment_bilateral.yaml"
    path.write_text(
        path.read_text().replace(
            "output: ../../datasets/rakuda-mock-bilateral", "output: datasets/bilateral"
        )
    )
    with Session.launch(path, log_dir=tmp_path / "logs") as s:
        s.wait_ready(30)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            nodes = s.status()
            received = (
                nodes.get("leader", {})
                .get("fields", {})
                .get("feedback", {})
                .get("received", 0)
            )
            if received > 0 and nodes.get("effort", {}).get("fields", {}).get(
                "rate_hz"
            ):
                break
            time.sleep(0.2)
        nodes = s.status()
    assert nodes["effort"]["fields"]["valid"] is False  # `none` never estimates
    assert nodes["controller"]["fields"]["feedback_gate"] is False
    leader = nodes["leader"]["fields"]
    assert leader["feedback"]["received"] > 0 and leader["feedback"]["gate"] is False
    assert "feedback_rejected" not in leader
