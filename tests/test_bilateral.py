import shutil
import time
from copy import deepcopy

import pytest

from roboloom.config import parse_experiment, read_experiment
from roboloom.core.protocol import Envelope, Publisher
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
    assert (tmp_path / "logs" / "robot_trace.npz").is_file()
    assert nodes["effort"]["fields"]["valid"] is False  # `none` never estimates
    assert nodes["controller"]["fields"]["feedback_gate"] is False
    leader = nodes["leader"]["fields"]
    assert leader["feedback"]["received"] > 0 and leader["feedback"]["gate"] is False
    assert "feedback_rejected" not in leader


def recorded_tree():
    tree = read_experiment(PATH)
    tree["estimators"]["effort"]["record"] = True
    tree["recorder"]["max_age_ms"]["effort"] = 300
    return tree


def test_recorded_estimator_adds_features_and_a_recorder_input():
    from roboloom.recording import features

    cfg = parse_experiment(recorded_tree())
    schema = features(cfg)
    assert schema["observation.effort_ext"]["shape"] == (12,)
    assert schema["observation.contact"]["shape"] == (1,)
    assert "observation.meta.effort.valid" in schema
    recorder = next(x for x in build_flow(cfg)["nodes"] if x["id"] == "recorder")
    assert recorder["inputs"]["effort"]["source"] == "effort/estimate"
    assert recorder["inputs"]["effort"]["queue_size"] == 15  # robot 30 Hz x 0.5 s
    unrecorded = parse_experiment(read_experiment(PATH))
    assert "observation.effort_ext" not in features(unrecorded)


def test_recorded_estimator_needs_a_max_age():
    tree = recorded_tree()
    del tree["recorder"]["max_age_ms"]["effort"]
    with pytest.raises(ValueError, match="max_age_ms.effort"):
        parse_experiment(tree)


def test_recorder_writes_external_effort_and_contact():
    from roboloom.recording import EpisodeRecorder

    cfg = parse_experiment(recorded_tree())
    recorder = EpisodeRecorder(cfg)
    t = time.monotonic_ns()
    ms = 1_000_000
    recorder.start("push", t, write=False)
    residual = [0.0] * 12
    residual[3] = 25.0
    est = Envelope(
        Estimator.kind,
        "effort",
        "boot",
        0,
        t - ms,
        t - ms,
        {
            "residual": residual,
            "valid": True,
            "contact": True,
            "joints": [],
            "unit": "mA",
        },
        t_receive_ns=t - ms,
    )
    recorder.ingest("effort", est)
    recorder.ingest(
        "action",
        Envelope(
            "action",
            "robot",
            "boot",
            1,
            t + 20 * ms,
            t + 20 * ms,
            {"valid": True, "positions": [2048] * 17, "command_seq": 1, "t_sent_ns": t},
            t_receive_ns=t + 21 * ms,
        ),
    )
    recorder.stop(t + 100 * ms)
    row = recorder.frames()[0]
    assert (
        row["observation.effort_ext"][3] == -25.0
    )  # external force opposes the residual
    assert row["observation.effort_ext.valid"][0] == 1
    assert row["observation.contact"][0] == 1
    assert row["observation.meta.effort.valid"][0] == 1


def test_robot_trace_keeps_published_state_per_tick(tmp_path):
    import numpy as np

    from roboloom.control.trace import RobotTrace
    from roboloom.robots.safety import FollowerSafety

    trace = RobotTrace(tmp_path / "robot_trace.npz", ["a", "b"], FollowerSafety.MODES)
    trace.add(
        1,
        {
            "positions": [1.0, 2.0],
            "velocities": None,
            "currents_mA": [3.0, 4.0],
            "target": [5.0, 6.0],
            "mode": "ACTIVE",
        },
    )
    trace.add(2, {"positions": [1.0, 2.0], "mode": "HOLD"})
    data = np.load(trace.save())
    assert list(data["joints"]) == ["a", "b"]
    assert [data["modes"][m] for m in data["mode"]] == ["ACTIVE", "HOLD"]
    assert data["measured_mA"][0].tolist() == [3.0, 4.0]
    assert data["target"][0].tolist() == [5.0, 6.0]
    assert np.isnan(data["velocities"]).all() and np.isnan(data["target"][1]).all()


def bilateral_tree(tmp_path, goal_mA=1000):
    """The shipped bilateral template, filled as `init` users do (ports, limits, models)."""
    from conftest import rakuda2_tree
    from test_tools import synthetic_models

    paths = synthetic_models(tmp_path)
    tree = rakuda2_tree("experiment_bilateral")
    for group in tree["inputs"]["leader"]["control"]:
        if group["law"] == "gravity_comp":
            group["gravity_model"] = str(paths[group["group"].split("_")[0]])
            group["range"] = [[500, 3500]] * 6
    robot = tree["robots"]["robot"]
    limits = robot["registers"]["current_limit"]
    for joint, value in limits.items():
        if value == "SET_FOLLOWER_ARM_GOAL_CURRENT_mA":
            limits[joint] = 1000
    for group in robot["control"]:
        if group.get("goal_current_mA") == "SET_FOLLOWER_ARM_GOAL_CURRENT_mA":
            group["goal_current_mA"] = goal_mA
    return tree


def test_bilateral_template_parses_with_hardware_checks(tmp_path):
    cfg = parse_experiment(bilateral_tree(tmp_path))
    assert not cfg.mock and set(cfg.estimators) == {"effort"}
    assert cfg.controllers["controller"].feedback.leader_joints == ["r_arm_el_yaw"]
    robot = cfg.robots["robot"]
    modes = robot.expected_eeprom()[2]["operating_mode"]
    assert modes["r_arm_el_yaw"] == 5 and modes["torso_yaw"] == 3
    assert modes["r_arm_grip"] == 5


def test_template_refuses_unfilled_or_too_high_goal_current(tmp_path):
    from conftest import rakuda2_tree

    with pytest.raises(ValueError, match="SET_FOLLOWER_ARM_GOAL_CURRENT_mA"):
        parse_experiment(rakuda2_tree("experiment_bilateral"))
    with pytest.raises(ValueError, match="exceeds registers.current_limit"):
        parse_experiment(bilateral_tree(tmp_path, goal_mA=1200))


def test_mock_follower_runs_arms_in_current_position_mode(tmp_path):
    from roboloom.robots.safety import FollowerSafety

    tree = bilateral_tree(tmp_path)
    tree["experiment"]["mode"] = "mock"
    cfg = parse_experiment(tree)
    robot = cfg.robots["robot"]
    bus = robot.open_device(True)
    safety = FollowerSafety(robot.safety_config(cfg.robot_id), bus)
    safety.start()
    try:
        raw = bus.bus
        elbow = robot.joint_names.index("r_arm_el_yaw")
        grip = robot.joint_names.index("r_arm_grip")
        assert raw.modes[elbow] == 5 and raw.modes[0] == 3
        assert raw.goal_current[elbow] == 1000 and raw.goal_current[grip] == 54
        assert all(raw.torque)
        state, _ = safety.tick()
        assert state.payload["mode"] == "HOLD"
    finally:
        bus.close()
