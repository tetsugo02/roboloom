# Extending roboloom

Decide first whether the change belongs in the user's project (downstream) or in roboloom
itself (upstream).

| Goal | Where |
| --- | --- |
| Own policy, own checkpoint loader | Downstream: `module:callable` ([policy.md](policy.md)) |
| Own collection/eval script, task prompts, episode filtering | Downstream: `Session` ([python-api.md](python-api.md)) |
| Simulation, tests, a simple one-follower robot with your own bus or sensor functions | Downstream: `InProcessSession.from_components` ([in-process.md](in-process.md)) |
| Another camera/sensor of a supported `type`, another node layout | Downstream: own options and node YAML in `config.yaml` |
| New robot, leader, hand-held input, sensor, controller or bus `type` | **Upstream** (a change to roboloom) |

## Why new device types cannot be added downstream

Each role maps `type:` to a class through a `Registry` (`roboloom.core.registry`):
`roboloom.robots.FOLLOWERS`, `roboloom.inputs.INPUTS`, `roboloom.sensors.SENSORS`,
`roboloom.controllers.CONTROLLERS` (and `roboloom.estimators.ESTIMATORS`). Their entries
are fixed in roboloom's `__init__.py` files. `Registry.register()` exists, but `Session`
starts every node as a new process (`<python> .../roboloom/runtime/node.py <node>
<config.yaml>`) that calls `load_config` again with only the built-in entries; there is no
entry-point or plugin discovery. A `FOLLOWERS.register(...)` in the user's script lets
`load_config` pass in that process, then the node fails with `unsupported follower type
'x'; expected one of ...`. Do not monkeypatch registries, and do not copy roboloom modules
into the project to fake a type.

## Downstream extension points that work

- **Policies.** `factory: "module:callable"` is imported inside the policy node: from
  installed packages first, then from `.roboloom/<robot>/` (e.g. `my_policy:load`). The
  same for `Session.launch(..., policy=..., policy_kwargs=...)` and `roboloom infer
  --policy`. Contract and examples: [policy.md](policy.md).
- **`InProcessSession.from_components`.** Any bus with `read_positions`, `write_positions`,
  `enable_torque`, `close` (`roboloom.drivers.base.JointBus`) and sensor callables
  returning `Sample(value, capture_ns)` or `None`. One follower; the follower checks
  still apply; an external bus is treated as worst case (`torque_off: falls`). Not for
  production collection.
- **Scripting `Session`.** Launch, `wait_ready`, `record`/`start`/`stop`/`save`/`discard`,
  `home`, `estop`, status listeners; run it from the project's own modules.
- **Own options and node files.** Node YAML and options in `.roboloom/<robot>/` are the
  user's. An option can add, replace or remove node files that use existing types:

```yaml
options:
  wrist:
    help: second RealSense on the wrist
    set:
      sensors.wrist: nodes/wrist_camera.yaml   # type: realsense_rgb; serial stays SET_ until the user gives it
    dataset: wrist                              # it changes the recorded features
```

Check with `roboloom validate --with wrist`. Node names become dataset feature names.

Bilateral control (`feedback:`, effort estimators) exists but is unverified and paused;
do not use it or build on it.

## Adding hardware upstream

Contributions follow the repository's AGENTS.md and the contribution page
(<https://tetsugo02.github.io/roboloom/en/contribution/>). Design rules: a new robot,
leader or controller must not change the behaviour of the others; hardware-specific
features stay behind the model's own declarations (safety traits, `effort_signal`,
`kinematics()`, `expected_eeprom`) instead of generic code. To develop against the
user's project, use a checkout: `uv add --editable ../roboloom`.

Steps for a new robot (compare `robots/rakuda2`, `robots/piper`, `robots/pika`):

1. `src/roboloom/robots/<model>/`: `spec.py` (joints, IDs, models, shared by its inputs),
   `follower.py` with a `roboloom.robots.base.Follower` subclass. It must declare
   `safety_traits` (or `declared_traits()`), else import raises `TypeError`; use
   `unknown` for what is not established. Implement `open_bus(mock)` (mock bus
   included), `device_ids()`, and `kinematics()` for `pose_ik` (URDF under `model/`).
2. Register it in `FOLLOWERS` (`src/roboloom/robots/__init__.py`). Leaders and hand-held
   devices go to `src/roboloom/inputs/<device>/` (`JointInput` or `PoseInput`) and
   `INPUTS`; new buses to `src/roboloom/drivers/`; sensors subclass their modality's
   base stream type (`ImageSensor`, `TactileImageSensor`, `PcmAudio`) and register in
   `SENSORS`; controllers subclass `roboloom.controllers.base.Controller`.
3. SDKs go into a new extra in `pyproject.toml` and are imported only when the type is
   chosen (the registry imports modules lazily).
4. Optional `template/` (`README.md`, `config.yaml`, `nodes/`, `calibration/`) with
   `SET_` placeholders for per-unit values, plus an entry in `TEMPLATES`
   (`src/roboloom/project.py`) so `roboloom init <model>` works.
5. Mock tests in `tests/`. Then `ruff check .`, `mypy src`, `pytest`.
6. Docs in both languages with the same paths: while unverified on hardware, a page under
   `docs/{en,ja}/contribution/` marked in development; once verified, Robots and Quick
   start pages. Add pages to `nav` in `mkdocs.yml` and `mkdocs.en.yml`; build with
   `uv run --group docs python scripts/docs.py build`.
7. This skill: `references/robots/<robot>.md`, a row in SKILL.md's status and reference
   tables, the extra in [installation.md](installation.md); `tests/test_agent_skills.py`
   checks links, imports and CLI commands.

Report mock tests, real-data checks and hardware verification separately; never present
unverified hardware behaviour as supported.
