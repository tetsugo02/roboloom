# Extending roboloom

Decide first whether the change belongs in the user's project (downstream) or in roboloom
itself (upstream).

| Goal | Where |
| --- | --- |
| Own policy, own checkpoint loader | Downstream: `module:callable` ([policy.md](policy.md)) |
| Own collection/eval script, task prompts, episode filtering | Downstream: `Session` ([python-api.md](python-api.md)) |
| Simulation, tests, a simple one-follower robot with your own bus or sensor functions | Downstream: `InProcessSession.from_components` ([in-process.md](in-process.md)) |
| Another camera/sensor of a supported `type`, another node layout | Downstream: own options and node YAML in `config.yaml` |
| New robot, leader, hand-held input, sensor, controller or estimator class | Downstream: `type: module:Class` in the node YAML (below); upstream when it should ship with roboloom |

## What a new type has to provide

- **Follower model**: joints, unit, safety traits, `open_bus` returning a `JointBus`
  (`read_positions`, `write_positions`, `enable_torque`, `close`; optional `read_state`,
  `read_health`). Optional: `PARTS` (joint groups several controllers may share, driven
  through `type: parts`) and `kinematics(part)` returning a `KinematicSpec` with the map
  from the follower's unit to the URDF's rad (`scale`, `offset`, `confirmed`).
- **Simulator**: another `JointBus` behind the same follower model; speak the real
  follower's unit so datasets and policies are shared. Controllers, IK, safety and
  recording do not change.
- **Pose device (VR, UMI-like)**: a `PoseInput` subclass; `pose_ik` works unchanged.
- **Joint leader**: a `JointInput`; with the follower's joint names and unit
  `type: joint` needs no table.
- `control:` laws (`roboloom.control`) assume a Dynamixel-like bus (counts, mA, operating
  modes); robots with their own position control (PiPER, Pika Gripper) refuse `control:`.

## A type of your own, downstream

A node YAML's `type` is a built-in name or a reference `module:Class` to a class of the
user's own code:

```yaml
# .roboloom/lab_arm/nodes/follower.yaml
type: my_arm:MyArm          # .roboloom/lab_arm/my_arm.py, or an installed my_lab.arm:MyArm
address: 10.0.0.2
control_hz: 50
limits: [...]
```

- The module is imported from the installed packages first, then from the robot's
  directory (`.roboloom/<robot>/`), in every node process.
- The class must subclass its role's base (`roboloom.robots.base.Follower`,
  `roboloom.inputs.base.JointInput` / `PoseInput`, `roboloom.core.source.Source`,
  `roboloom.controllers.base.Controller`, `roboloom.estimators.base.Estimator`); another
  object is refused on loading (`... is not a Follower subclass`).
- `keys = (*FOLLOWER_KEYS, "address")` on the class lists the YAML keys it reads; any
  other key is then refused on loading. A class without `keys` of its own is not checked.
- A follower also needs `safety_traits` and `open_bus(mock)` (a mock bus when `mock`).
- `Registry.register()` in a script does **not** work: every node is a new process that
  loads the configuration again. Name the class by reference. Do not monkeypatch
  registries or copy roboloom modules into the project.

Working example in a roboloom checkout: `examples/own_robot/` (`my_arm.py`, node YAML,
`mock.yaml`).

```bash
uv run roboloom init lab_arm --template examples/own_robot   # or --template my_lab.robots.arm
uv run roboloom infer lab_arm --mock --seconds 5 --plain
```

`roboloom init <name> --template <package or directory>` copies a template roboloom does
not ship (`<package>/template/`, or a directory holding `config.yaml`); the class's module
can sit in the template so it lands next to `config.yaml`. `--update` finds the template
again through `.template.json`.

## Downstream extension points that work

- **Types.** `type: module:Class` (above).
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
6. Docs in both languages with the same paths: pages under `docs/{en,ja}/robots/<robot>/`
   (overview, controllers, sensors), a row in `get-started/support-matrix.md`, and a
   tutorial; label anything not verified on hardware with a status from
   `reference/status-labels.md`. Add pages to `nav` in `mkdocs.yml` and `mkdocs.en.yml`;
   build with `uv run --group docs python scripts/docs.py build`.
7. This skill: `references/robots/<robot>.md`, a row in SKILL.md's status and reference
   tables, the extra in [installation.md](installation.md); `tests/test_agent_skills.py`
   checks links, imports and CLI commands.

Report mock tests, real-data checks and hardware verification separately; never present
unverified hardware behaviour as supported.
