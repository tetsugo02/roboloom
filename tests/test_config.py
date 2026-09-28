from copy import deepcopy

import pytest

from roboloom.config import parse_experiment, read_experiment
from roboloom.recording import features
from roboloom.runtime.flow import build_flow

PATH = "examples/mock/experiment.yaml"


def test_validate_rejects_duplicate_devices_and_bad_mapping():
    tree = read_experiment(PATH)
    duplicate = deepcopy(tree)
    duplicate["sensors"]["digit_right"]["serial"] = duplicate["sensors"]["digit_left"]["serial"]
    with pytest.raises(ValueError, match="duplicate"):
        parse_experiment(duplicate)
    wrong = deepcopy(tree)
    wrong["controllers"]["controller"]["joints"][0]["leader"] = "head_yaw"
    with pytest.raises(ValueError, match="mapping"):
        parse_experiment(wrong)
    flow = build_flow(parse_experiment(tree))
    assert len(flow["nodes"]) == 9
    assert next(x for x in flow["nodes"] if x["id"] == "robot")["restart_policy"] == "never"


def test_unknown_types_and_dangling_references_fail_before_opening_devices():
    tree = read_experiment(PATH)
    unknown = deepcopy(tree)
    unknown["sensors"]["camera"]["type"] = "thermal"
    with pytest.raises(ValueError, match="unsupported sensor type"):
        parse_experiment(unknown)
    dangling = deepcopy(tree)
    dangling["controllers"]["controller"]["input"] = "spacemouse"
    with pytest.raises(ValueError, match="configured input"):
        parse_experiment(dangling)


def test_sensors_are_selected_by_name_and_type():
    tree = read_experiment(PATH)
    tree["sensors"]["wrist"] = {**tree["sensors"]["camera"], "serial": "mock-wrist"}
    tree["recorder"]["max_age_ms"]["wrist"] = 300
    cfg = parse_experiment(tree)
    assert "observation.images.wrist" in features(cfg)
    recorder = next(x for x in build_flow(cfg)["nodes"] if x["id"] == "recorder")
    assert recorder["inputs"]["wrist"] == "wrist/sample"
