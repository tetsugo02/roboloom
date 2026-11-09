"""Tracking systems (`trackers:`): configuration and the dataflow that shares one."""

from __future__ import annotations

import copy

import pytest
from conftest import rakuda2_tree

from roboloom.config import parse_config, read_config
from roboloom.runtime.flow import build_flow
from roboloom.trackers.base import MockTrackerReader, TrackedPose, Tracker
from roboloom.trackers.libsurvive import Libsurvive

PIPER = ".roboloom/piper-mock/config.yaml"
HANDHELD = ".roboloom/pika-handheld-mock/config.yaml"


def nodes(tree: dict) -> dict:
    return {n["id"]: n for n in build_flow(parse_config(tree))["nodes"]}


def test_one_tracker_node_serves_both_senses_and_is_not_recorded():
    tree = read_config(PIPER)
    cfg = parse_config(copy.deepcopy(tree))
    assert list(cfg.trackers) == ["lighthouse"]
    flow = nodes(tree)
    lighthouse = flow["lighthouse"]
    assert lighthouse["outputs"] == ["poses", "status"]
    assert set(lighthouse["inputs"]) == {"session", "tick"}
    for sense in ("left_sense", "right_sense"):
        assert flow[sense]["inputs"]["tracker"] == {
            "source": "lighthouse/poses",
            "queue_size": 1,
            "queue_policy": "drop_oldest",
        }
    # the senses' rate (their followers') sets the tracker's, and the session waits for it
    assert lighthouse["inputs"]["tick"] == flow["left_sense"]["inputs"]["tick"]
    assert "lighthouse_status" in flow["session"]["inputs"]
    assert not any("lighthouse" in str(s) for s in flow["recorder"]["inputs"].values())


def test_without_trackers_nothing_changes():
    flow = nodes(rakuda2_tree())
    assert "tracker" not in flow["leader"]["inputs"]
    assert not any(n["outputs"] == ["poses", "status"] for n in flow.values())


def test_a_tracker_rate_can_be_set():
    tree = read_config(HANDHELD)
    tree["trackers"]["lighthouse"]["poll_hz"] = 250
    assert nodes(tree)["lighthouse"]["inputs"]["tick"] == "dora/timer/hz/250"


def test_the_configuration_checks_the_tracking_system():
    tree = read_config(PIPER)
    bad = copy.deepcopy(tree)
    bad["inputs"]["left_sense"]["tracker"]["system"] = "optitrack"
    with pytest.raises(ValueError, match="'optitrack' is not a node under trackers"):
        parse_config(bad)
    two = copy.deepcopy(tree)
    two["trackers"]["second"] = dict(two["trackers"]["lighthouse"])
    with pytest.raises(ValueError, match="duplicate port or sensor ID"):
        parse_config(two)  # one libsurvive context per host
    same = copy.deepcopy(tree)
    same["inputs"]["right_sense"]["tracker"]["serial"] = "LHR-MOCK0001"
    with pytest.raises(ValueError, match="duplicate port or sensor ID"):
        parse_config(same)
    for key, value, error in (
        ("type", "steamvr", "unsupported tracker type"),
        ("args", "--lighthouse-gen 2", "list of strings"),
        ("args", ["SET_ARG"], "template values still to fill"),
        ("poll_hz", 0, "positive"),
        ("tracker_args", [], "unknown keys"),
    ):
        broken = copy.deepcopy(tree)
        broken["trackers"]["lighthouse"][key] = value
        with pytest.raises(ValueError, match=error):
            parse_config(broken)


def test_poses_travel_as_plain_payloads():
    poses = {
        "LHR-A": TrackedPose((0.1, 0.2, 0.3), (0.0, 0.0, 0.0, 1.0), 5, True),
        "LHR-B": TrackedPose((1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), 6, False),
    }
    assert Tracker.decode(Tracker.encode(poses)) == poses
    assert Tracker.decode({}) == {}


def test_the_mock_tracker_sees_nothing_and_opens_no_hardware():
    tracker = Libsurvive("lighthouse", {"type": "libsurvive"})
    reader = tracker.open(mock=True)
    assert isinstance(reader, MockTrackerReader) and reader.read() == {}
    assert tracker.device_ids() == ("libsurvive",)
