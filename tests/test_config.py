from copy import deepcopy

import pytest

from roboloom.config import load_experiment, validate
from roboloom.flow import build_flow


def test_validate_rejects_duplicate_devices_and_bad_mapping():
    cfg = load_experiment("examples/mock/experiment.yaml")
    duplicate = deepcopy(cfg)
    duplicate["nodes"]["digit_right"]["serial"] = duplicate["nodes"]["digit_left"]["serial"]
    with pytest.raises(ValueError, match="duplicate"):
        validate(duplicate)
    wrong = deepcopy(cfg)
    wrong["nodes"]["controller"]["joints"][0]["leader"] = "head_yaw"
    with pytest.raises(ValueError, match="mapping"):
        validate(wrong)
    flow = build_flow(cfg)
    assert len(flow["nodes"]) == 9
    assert next(x for x in flow["nodes"] if x["id"] == "robot")["restart_policy"] == "never"
