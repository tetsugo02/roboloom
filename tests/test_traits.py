"""Safety traits: every model declares them, and prompts and choices follow them."""

from __future__ import annotations

import pytest

from roboloom.config import load_config
from roboloom.control.device import GroupSpec
from roboloom.core.traits import (
    WORST_CASE,
    SafetyTraits,
    ending_note,
    precautions,
)
from roboloom.inputs.base import JointInput
from roboloom.robots.base import Follower
from roboloom.runtime.session import Session
from roboloom.ui.render import follower as render_follower

LIMITS = [{"name": "j", "min": -1, "max": 1, "max_speed": 1, "max_jump": 1}]


def external(**cfg) -> Follower:
    return Follower("arm", {"limits": LIMITS, "control_hz": 30, **cfg}, ["j"], "rad")


def test_a_model_that_declares_nothing_is_refused_at_import():
    with pytest.raises(TypeError, match="declare safety_traits"):

        class Silent(Follower):
            model = "silent"

    with pytest.raises(TypeError, match="declare safety_traits"):

        class SilentLeader(JointInput):
            pass

    class Declared(Follower):
        safety_traits = SafetyTraits(torque_off="stays", unattended="holds")

    assert Declared.safety_traits.holds_unattended


def test_traits_reject_unknown_values():
    with pytest.raises(ValueError, match="torque_off"):
        SafetyTraits(torque_off="floats", unattended="holds")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unattended"):
        SafetyTraits(torque_off="falls", unattended="maybe")  # type: ignore[arg-type]


def test_an_external_bus_gets_the_worst_case_and_a_measurement_fills_it_in():
    assert external().traits() == WORST_CASE
    assert external(unattended="holds").traits() == SafetyTraits("falls", "holds")
    with pytest.raises(ValueError, match="one of holds, torque_off"):
        external(unattended="unknown").traits()


def test_rakuda2_holds_only_without_current_mode_laws(tmp_path):
    from dataclasses import replace

    from conftest import mock_project

    project = mock_project(tmp_path / ".roboloom")
    cfg = load_config(project / "config.yaml", options=[])
    follower = cfg.followers["follower"]
    assert follower.traits() == SafetyTraits("falls", "holds")
    assert cfg.inputs["leader"].safety_traits.torque_off == "falls"
    # current-based position (the bilateral follower) still holds its goal position;
    # a current-mode law goes limp when the node closes the bus (and on the watchdog)
    follower.control = [GroupSpec("arm", "current_position", ("torso_yaw",), {})]
    assert follower.traits().unattended == "holds"
    follower.control = [replace(follower.control[0], law="gravity_comp")]
    assert follower.traits() == SafetyTraits("falls", "torque_off")


def test_a_measurement_cannot_override_what_the_model_declares(tmp_path):
    import shutil

    import yaml

    target = tmp_path / "mock"
    shutil.copytree("examples/mock", target, ignore=shutil.ignore_patterns("logs"))
    path = target / "nodes" / "follower.yaml"
    data = yaml.safe_load(path.read_text())
    data["unattended"] = "torque_off"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(Exception, match="declares 'holds'"):
        load_config(target / "config.yaml", options=[])


def test_precautions_name_what_falls_and_what_lets_go():
    devices = {
        "left": SafetyTraits("falls", "unknown"),
        "gripper": SafetyTraits("lets_go", "holds"),
        "wrist": SafetyTraits("stays", "holds"),
    }
    text = precautions(devices)
    assert "support left (falls" in text
    assert "take any object out of gripper" in text
    assert "wrist" not in text
    assert precautions({"wrist": devices["wrist"]}) == ""
    note = ending_note({"left": devices["left"]})
    assert note.startswith("left may go limp (not measured: roboloom check-hold): ")


def session_for(cfg) -> Session:
    session = Session.__new__(Session)
    session.cfg = cfg
    return session


def test_session_holds_only_followers_that_hold_unattended(tmp_path):
    from conftest import mock_project

    project = mock_project(tmp_path / ".roboloom")
    session = session_for(load_config(project / "config.yaml", options=[]))
    assert session.held == ["follower"]
    assert set(session.limp_at_end) == {"leader"}  # the leader's control laws
    session.cfg.followers["follower"].cfg["unattended"] = "torque_off"  # not declared
    with pytest.raises(ValueError, match="declares 'holds'"):
        _ = session.held
    session.cfg.followers["follower"] = external()  # the worst case
    assert session.held == []  # nothing holds: quit offers no "hold"
    assert set(session.limp_at_end) == {"leader", "follower"}
    assert "support leader, follower" in session.release_note()


def test_the_screen_says_what_to_do_about_a_follower_left_alone():
    _, released = render_follower(
        {"mode": "RELEASED", "torque_off": "falls", "unattended": "holds"}
    )
    assert "torque off: support it" in released.plain
    _, fault = render_follower(
        {"mode": "FAULT", "torque_off": "falls", "unattended": "unknown"}
    )
    assert "may go limp: support it" in fault.plain
    _, held = render_follower(
        {"mode": "FAULT", "torque_off": "falls", "unattended": "holds"}
    )
    assert "support" not in held.plain
