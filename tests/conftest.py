import itertools
import json
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from roboloom.config import load_config, read_config
from roboloom.core.protocol import Envelope

TESTS_DIR = Path(__file__).resolve().parent
SECOND_NS = 1_000_000_000


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--shard",
        default=None,
        help="Run 1-based shard INDEX/TOTAL of collected tests (e.g. --shard=1/3).",
    )


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if shutil.which("dora") is None:
        skip_dora = pytest.mark.skip(reason="needs dora")
        for item in items:
            if item.get_closest_marker("e2e") is not None:
                item.add_marker(skip_dora)
    spec = config.getoption("--shard")
    if not spec:
        return
    index_s, sep, total_s = str(spec).partition("/")
    if not sep or not index_s.isdigit() or not total_s.isdigit():
        raise pytest.UsageError(f"--shard must be INDEX/TOTAL, got {spec!r}")
    index, total = int(index_s), int(total_s)
    if not (1 <= index <= total):
        raise pytest.UsageError(f"--shard INDEX must be in 1..{total}, got {index}")
    selected = items[index - 1 :: total]
    deselected = [item for i, item in enumerate(items) if i % total != index - 1]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected


TEMPLATE = Path("src/roboloom/robots/rakuda2/template")


def rakuda2_tree(options: list[str] | None = None) -> dict:
    """The shipped Rakuda-2 template with these launch options (None: the defaults) and its
    device placeholders filled, as `init` users do."""
    tree = read_config(TEMPLATE / "config.yaml", options)
    if "leader" in tree["inputs"]:
        tree["inputs"]["leader"]["port"] = "/dev/serial/by-id/leader"
    tree["followers"]["follower"]["port"] = "/dev/serial/by-id/follower"
    for limit in tree["followers"]["follower"]["limits"]:
        limit["min"], limit["max"] = 1000, 3000
    serials = {"camera": "142122070848", "digit_left": "D1", "digit_right": "D2"}
    for sensor, serial in serials.items():
        if sensor in tree["sensors"]:
            tree["sensors"][sensor]["serial"] = serial
    return tree


def mock_project(root: Path) -> Path:
    """`roboloom init rakuda2` under `root`, filled and switched to mock mode, as files
    (the dora nodes read the configuration from disk). Returns the robot's project directory."""
    from roboloom.project import init_project

    init_project("rakuda2", root)
    filled = {
        "SET_LEADER_PORT": "/dev/leader",
        "SET_FOLLOWER_PORT": "/dev/follower",
        "SET_FOLLOWER_ARM_GOAL_CURRENT_mA": "1000",
        "SET_REALSENSE_SERIAL": "RS1",
        "SET_DIGIT_LEFT_SERIAL": "D1",
        "SET_DIGIT_RIGHT_SERIAL": "D2",
        "dataset_fps: 15": "mode: mock\ndataset_fps: 15",
        # the mock follower starts at 2048; a leader trigger resting there is aligned
        "rest: 2500": "rest: 2048",
    }
    used: set[str] = set()
    for path in (root / "rakuda2").rglob("*.yaml"):
        if path.name == "mock.yaml":
            continue  # the template's mock stand-ins are keyed by the SET_ names
        text = path.read_text()
        for old, new in filled.items():
            if old in text:
                used.add(old)
                text = text.replace(old, new)
        path.write_text(text)
    # a template edit must not silently leave a placeholder or the hardware mode in place
    assert used == set(filled), f"template no longer contains {set(filled) - used}"
    return root / "rakuda2"


def dual_mock(root: Path) -> Path:
    """examples/mock with a second leader, follower and joint controller (`left`), as
    files: two followers in one configuration. Returns the config.yaml path."""
    import shutil

    import yaml

    target = root / "dual"
    shutil.copytree("examples/mock", target, ignore=shutil.ignore_patterns("logs"))
    nodes = target / "nodes"
    for kind, name in (("leader", "left_leader"), ("follower", "left")):
        data = yaml.safe_load((nodes / f"{kind}.yaml").read_text())
        data["port"] = f"mock://{name}"
        (nodes / f"{name}.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    controller = yaml.safe_load((nodes / "controller.yaml").read_text())
    controller.update(input="left_leader", followers=["left"])
    (nodes / "left_controller.yaml").write_text(yaml.safe_dump(controller))
    recorder = yaml.safe_load((nodes / "recorder.yaml").read_text())
    recorder["max_age_ms"].update(left_leader=300, left=300)
    (nodes / "recorder.yaml").write_text(yaml.safe_dump(recorder))
    config = yaml.safe_load((target / "config.yaml").read_text())
    config["inputs"]["left_leader"] = "nodes/left_leader.yaml"
    config["controllers"]["left_controller"] = "nodes/left_controller.yaml"
    config["followers"]["left"] = "nodes/left.yaml"
    config["output"] = "datasets/dual"
    del config["options"]
    for sensor in ("digit_left", "digit_right", "audio"):
        del config["sensors"][sensor]
    path = target / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path


class FakeClock:
    """Deterministic monotonic clock and sleep replacement for unit tests."""

    def __init__(self, start: float = 50.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeDataset:
    """Minimal in-memory LeRobot dataset stub recording add_frame() rows."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    def add_frame(self, frame: dict) -> None:
        self.frames.append(frame)


def add_tests_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prepend tests/ to PYTHONPATH so dora node subprocesses can import test policies."""
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(TESTS_DIR), *(p for p in existing.split(os.pathsep) if p)]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(parts))


@pytest.fixture
def tests_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    add_tests_pythonpath(monkeypatch)


def make_fake_session(
    tmp_path: Path,
    cfg=None,
    *,
    client=None,
    process=None,
    **attrs,
):
    """Build a lightweight Session instance without spawning dora."""
    from roboloom.runtime.session import Session

    session = Session.__new__(Session)
    session.cfg = cfg if cfg is not None else load_config("examples/mock/config.yaml")
    if client is None:
        client = MagicMock()
        client.status.return_value = {"nodes": {}}
        client.new_reports.return_value = []
    session.client = client
    if process is None:
        process = MagicMock()
        process.poll.return_value = None
        process.returncode = None
    session.process = process
    session.log_dir = tmp_path
    session.log_path = tmp_path / "dora.log"
    session.log_path.write_text("")
    session.fifo = tmp_path / "session.fifo"
    session._workdir = MagicMock()
    session._ids = itertools.count(1)
    session._closed = False
    session._cancel_local = threading.local()
    session._reports = []
    session._recorded = []
    session._episode = None
    session._saved = 0
    session._queued_saves = {}
    session._save_progress = {}
    session._recorder_closed = False
    session._lock = threading.RLock()
    session._listeners = []
    session.screen = None
    session.operator = None
    session._lifeline = None
    for key, value in attrs.items():
        setattr(session, key, value)
    return session


def run_session_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reads,
    *,
    cfg=None,
    events=None,
    step_ns: int = SECOND_NS // 4,
    start_ns: int = SECOND_NS,
):
    """Run roboloom.runtime.node._session on scripted FIFO reads and optional dora events.

    Returns (sent_payloads, reports, status_path, fifo, work_dir).
    """
    from roboloom.runtime import node as runtime

    config = cfg if cfg is not None else load_config("examples/mock/config.yaml")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    fifo = tmp_path / "session.fifo"
    os.mkfifo(fifo)
    status_path = work / "status.json"
    monkeypatch.setenv("ROBOLOOM_SESSION_FIFO", str(fifo))
    monkeypatch.setenv("ROBOLOOM_REPORT_PATH", str(work / "report.jsonl"))
    monkeypatch.setenv("ROBOLOOM_STATUS_PATH", str(status_path))
    now = start_ns
    script = iter(reads)
    seen: list[dict] = []

    def read(fd: int, count: int) -> bytes:
        nonlocal now
        now += step_ns
        item = next(script)
        if isinstance(item, BaseException):
            raise item
        return item

    real_open = open
    kept_reports = tmp_path / "reports.jsonl"

    def keep(path, mode="r", *args, **kwargs):
        if str(path).endswith("report.jsonl") and "a" in mode:
            return real_open(kept_reports, mode, *args, **kwargs)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(runtime.os, "read", read)
    monkeypatch.setattr(runtime.time, "monotonic_ns", lambda: now)

    if events is None:

        def event(node):
            if seen and seen[-1]["command"] == "quit":
                return "report", Envelope(
                    "report", "recorder", "boot", 1, now, now, {"command": "quit"}
                )
            return None, None
    elif callable(events):

        def event(node):
            return events(node, now)
    else:
        ev_iter = iter(events)

        def event(node):
            return next(ev_iter)

    monkeypatch.setattr(runtime, "_event", event)
    monkeypatch.setattr("builtins.open", keep)

    class _Node:
        def send_output(self, output: str, value: bytes) -> None:
            assert output == "control"
            seen.append(Envelope.decode(value).payload)

    runtime._session(_Node(), config)
    lines = kept_reports.read_text().splitlines() if kept_reports.exists() else []
    return seen, [json.loads(line) for line in lines], status_path, fifo, work
