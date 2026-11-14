"""A key nothing reads is refused when the configuration is loaded: a misspelled one
(`torqe: false`) would otherwise be ignored in silence and the default used."""

from __future__ import annotations

from copy import deepcopy

import pytest
from conftest import rakuda2_tree

from roboloom.config import _check_keys, parse_config, read_config
from roboloom.controllers import CONTROLLERS
from roboloom.core.checks import unknown_keys
from roboloom.errors import ConfigError
from roboloom.estimators import ESTIMATORS
from roboloom.inputs import INPUTS
from roboloom.robots import FOLLOWERS
from roboloom.robots.base import Follower
from roboloom.sensors import SENSORS


def _rakuda2(change) -> None:
    tree = rakuda2_tree()
    tree["settings"]["mode"] = "mock"
    parse_config(deepcopy(tree))  # loads as it is
    change(tree)
    parse_config(tree)


def _mock(change) -> None:
    tree = read_config("examples/mock/config.yaml")
    parse_config(deepcopy(tree))
    change(tree)
    parse_config(tree)


def _health(tree: dict) -> None:
    tree["followers"]["follower"]["health"] = {
        "every_ticks": 10,
        "max_temprature_c": 70,
    }


def _free_group(tree: dict) -> None:
    groups = tree["inputs"]["leader"]["control"]
    next(g for g in groups if g["law"] == "free")["kd"] = 0.5


@pytest.mark.parametrize(
    ("load", "change", "message"),
    [
        (
            _rakuda2,
            lambda t: t["followers"]["follower"].update(torqe=False),
            r"followers\.follower: unknown keys torqe \(did you mean torque\?\)",
        ),
        (
            _rakuda2,
            lambda t: t["followers"]["follower"]["limits"][0].update(max_sped=100),
            r"limits \(torso_yaw\): unknown keys max_sped \(did you mean max_speed\?\)",
        ),
        (_rakuda2, _health, r"follower\.health: unknown keys max_temprature_c"),
        # a law reads its own keys only: damping means nothing to a free joint
        (_rakuda2, _free_group, r"leader\.control\.\w+ \(law free\): unknown keys kd"),
        (
            _rakuda2,
            lambda t: t["inputs"]["leader"].update(pol_hz=60),
            r"inputs\.leader: unknown keys pol_hz \(did you mean poll_hz\?\)",
        ),
        (
            _rakuda2,
            lambda t: t["sensors"]["camera"].update(widht=640),
            r"sensors\.camera: unknown keys widht \(did you mean width\?\)",
        ),
        (
            _rakuda2,
            lambda t: t["controllers"]["controller"].update(max_sped=100),
            r"controllers\.controller: unknown keys max_sped",
        ),
        (
            _rakuda2,
            lambda t: t["recorder"].update(grace_m=100),
            r"recorder: unknown keys grace_m \(did you mean grace_ms\?\)",
        ),
        (_rakuda2, lambda t: t["session"].update(typ=1), r"session: unknown keys typ"),
        (
            _mock,
            lambda t: t["controllers"]["controller"]["joints"][0].update(scal=2),
            r"controller\.joints: unknown keys scal",
        ),
    ],
)
def test_a_key_nothing_reads_is_refused_with_the_nearest_name(load, change, message):
    with pytest.raises(ConfigError, match=message):
        load(change)


def test_the_message_lists_what_is_read():
    with pytest.raises(ConfigError, match=r"it reads max, min$"):
        unknown_keys({"min": 0, "maxx": 1}, ("min", "max"), "limits")
    unknown_keys({"min": 0, "__file__": "x"}, ("min",), "limits")  # added on loading


@pytest.mark.parametrize(
    "registry",
    [FOLLOWERS, INPUTS, SENSORS, CONTROLLERS, ESTIMATORS],
    ids=lambda r: r.kind,
)
def test_every_type_of_the_package_says_which_keys_it_reads(registry):
    for name in registry.names():
        cls = registry.get(name)
        assert "keys" in vars(cls), f"{registry.kind} type {name}: declare `keys`"
        assert "type" in cls.keys


def test_a_class_that_does_not_declare_its_keys_is_not_checked():
    class Mine(Follower):  # an extension that reads a key of its own
        safety_traits = Follower.safety_traits

    cfg = {"address": "10.0.0.2"}
    _check_keys(Mine.__new__(Mine), cfg, "followers.mine")  # no `keys` of its own

    class Declared(Mine):
        safety_traits = Follower.safety_traits
        keys = (*Follower.keys, "address")

    _check_keys(Declared.__new__(Declared), cfg, "followers.mine")
    with pytest.raises(ConfigError, match="unknown keys adress"):
        _check_keys(Declared.__new__(Declared), {"adress": 1}, "followers.mine")
