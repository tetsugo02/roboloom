---
name: roboloom
description: >-
  Use roboloom (robot teleoperation, LeRobotDataset recording and policy inference on
  dora-rs, for arms such as Rakuda2) from a project that depends on it. Use when writing
  Python with roboloom.Session, roboloom.setup or InProcessSession; editing
  .roboloom/<robot>/config.yaml or its node YAML; choosing launch options; running the
  roboloom CLI (init, validate, run, record, infer, commission, identify-gravity, ...);
  plugging in a policy; or training LeRobot policies on roboloom datasets.
metadata:
  roboloom-version: "0.1.0"
---

# roboloom

roboloom is a Python package (Python 3.12, `uv`) that runs a robot's teleoperation,
sensors, recorder and policy as a **dora-rs dataflow** and saves episodes as
**LeRobotDataset 0.6.1**. Everything the CLI does is also a Python function.

Public docs: <https://tetsugo02.github.io/roboloom/en/> (Japanese: `/ja/`).
Choose robot extras (`rakuda2`, or `piper,pika`) separately from shared features
(`record`, `hardware`, `digit`, `policy`, `train`); see [installation](references/installation.md).
This skill matches roboloom `0.1.0`; if `uv run roboloom skills check` says it is
outdated, run `uv run roboloom skills install --force`.

## Mental model

- **One robot = one directory** `.roboloom/<robot>/` in the user's project root, created
  by `roboloom init <robot>`. It holds `config.yaml`, node YAML under `nodes/`,
  `calibration/`, `poses/`, and (git-ignored) `logs/` and `datasets/`.
- `config.yaml` names nodes by **role**: `inputs` (leader arms, hand-held devices),
  `controllers` (`joint`, `pose_ik`, `policy`), `followers` (driven arms/grippers),
  `sensors`, `estimators`, `trackers` (a tracking system several inputs share, e.g.
  libsurvive for Pika Senses), plus `recorder` and `session`. Each node YAML's `type` picks
  the implementation. **Node names become dora IDs and dataset feature names.**
- **Launch options** (`options:` in `config.yaml`) swap node files at launch: e.g.
  `digit`, `gravity`, `policy`. Options with a `dataset:` name append it to `repo_id` and
  `output` (`local/rakuda2` + `digit` → `local/rakuda2-digit`), so different feature
  layouts never share a dataset.
- **Real hardware is the default.** `--mock` (CLI) / `mock=True` (Python) runs mock
  devices. `mode: mock` in YAML also works; the flag wins.
- `SET_...` values in the template are per-robot measurements (ports, serials, limits).
  Nothing runs while one remains; `roboloom validate` lists them with their location.
- Three entry points:
  - `roboloom.Session` – launches the dataflow and sends start/stop/save/task. Control
    loops run in their own processes, so a slow user script never disturbs them.
  - `roboloom.setup` – commissioning and measurement (EEPROM, travel, gravity model),
    returning dataclasses; human steps go through an `Operator`.
  - `roboloom.InProcessSession` – everything on the caller's thread, one follower; for
    tests, simulation and simple robots.

## Rules for agents

1. **Never energize or move hardware on your own.** Do not run, without the user
   explicitly asking, any command that opens real devices: `run`, `record`, `infer`
   without `--mock`, `commission`, `identify-gravity --collect`, `tune-gravity`,
   `gravity-check`, `watchdog-test`, `check-hold`, or a script calling `Session.launch`
   on hardware. Prefer `roboloom validate` (opens nothing) and `--mock` / `mock=True`.
   `probe` only reads, but it still needs the bus free.
2. **Never invent `SET_` values** (ports, serial numbers, IDs, joint limits, currents).
   Ask the user or tell them which measurement step produces the value. Never copy mock
   joint ranges or speeds into a hardware configuration.
3. **Keep units.** Rakuda2 joints are raw Dynamixel counts and current is mA; PiPER is rad
   and N·m. Do not convert units in configuration or policy outputs.
4. **Do not delete or overwrite datasets** to "fix" an append error; change `output` or
   add an option `dataset:` name instead (moving the old dataset away is the user's call).
   Commit `.roboloom/**/*.yaml`; never commit
   `*.npz`, `logs/`, `datasets/`.
5. **Say what is verified.** Features marked *mock only* below have not run on hardware;
   tell the user so when you use them. Do not set up or tune the `bilateral` option.
6. When the user will run hardware, remind them: support the arms, use `torque: false` on
   the follower for the first path check, and end with `stop` → `save`/`discard` → `quit`
   (choose hold or supported release explicitly).

## Status of features

| Feature | Status | Reference |
| --- | --- | --- |
| Rakuda2 follower + Rakuda-mini leader (`joint` controller), gravity-compensated leader | Hardware-verified | [robots/rakuda2.md](references/robots/rakuda2.md) |
| RealSense RGB (`realsense_rgb`), DIGIT (`digit`) | Hardware-verified | [sensors.md](references/sensors.md) |
| Leader joint locking (`law: position`), `couplings`, `home` moves | Mock only | [robots/rakuda2.md](references/robots/rakuda2.md) |
| Own policies (`type: policy`) | Used with Rakuda2 config and mock | [policy.md](references/policy.md) |
| LeRobot checkpoints (`roboloom.policy.lerobot:load`), `lerobot-train` | Mock only (PiPER + Pika) | [policy.md](references/policy.md) |
| PiPER follower, Pika Gripper, Pika Sense + `pose_ik` | In development, mock only | [robots/piper-pika.md](references/robots/piper-pika.md) |
| Hand-held Pika Sense collection, `convert-handheld` | In development, mock only | [robots/handheld.md](references/robots/handheld.md) |
| `opencv_rgb` web camera (Linux/macOS/Windows driver only) | Mock only; hardware unverified; Windows Session excluded | [sensors.md](references/sensors.md) |
| `v4l2_rgb` fisheye camera (Pika wrist cameras) | In development, mock only | [sensors.md](references/sensors.md) |
| `pcm_mono` microphone | Not in the guides; mock only here | [sensors.md](references/sensors.md) |
| `bilateral` option (force feedback) | Not verified on hardware; paused – do not use | – |

## Install (in the user's uv project)

```bash
uv add git+https://github.com/tetsugo02/roboloom.git                                      # shared runtime, config, CLI, mocks
uv add git+https://github.com/tetsugo02/roboloom.git --extra rakuda2                       # + Dynamixel SDK
uv add git+https://github.com/tetsugo02/roboloom.git --extra piper --extra pika             # + PiPER SDK, IK, Pika tracker/cameras
uv add git+https://github.com/tetsugo02/roboloom.git --extra rakuda2 --extra record --extra hardware --extra digit  # Rakuda2 collection + sensors
```

`project.requires-python` must be `">=3.12,<3.13"`. Other extras: `record`, `hardware`, `digit`, `ik`,
`policy`, `train`. Run everything from the project root with `uv run`. Details:
[installation.md](references/installation.md).

## Which reference to read

| Task | Read |
| --- | --- |
| Install, extras, pin or update roboloom, agent skill install | [installation.md](references/installation.md) |
| Create `.roboloom/<robot>/`, what to commit, fill `SET_` values | [project-layout.md](references/project-layout.md) |
| Edit `config.yaml` / node YAML, launch options, units, safety traits | [configuration.md](references/configuration.md) |
| Script collection or inference with `Session` | [python-api.md](references/python-api.md) |
| Commission EEPROM, measure travel, identify and tune gravity | [setup.md](references/setup.md) |
| CLI commands and flags, operator screen keys | [cli.md](references/cli.md) |
| Dataset features, quality warnings, resuming, training data | [recording.md](references/recording.md) |
| Write a policy, load a LeRobot checkpoint, train with `lerobot-train` | [policy.md](references/policy.md) |
| Run in one process, tests, custom buses and sensors | [in-process.md](references/in-process.md) |
| Follower safety (clamp, HOLD, FAULT), stop and release | [safety.md](references/safety.md) |
| An error message | [troubleshooting.md](references/troubleshooting.md) |
| Rakuda2 joints, options, checks | [robots/rakuda2.md](references/robots/rakuda2.md) |
| PiPER, Pika Gripper, Pika Sense | [robots/piper-pika.md](references/robots/piper-pika.md) |
| Hand-held collection and conversion | [robots/handheld.md](references/robots/handheld.md) |
| RealSense, DIGIT, V4L2, audio | [sensors.md](references/sensors.md) |
| Add a new robot, sensor or input type | [extending.md](references/extending.md) |

## Minimal examples

Create and check a configuration without devices:

```bash
uv run roboloom init rakuda2          # .roboloom/rakuda2/ from the packaged template
uv run roboloom validate --with digit # lists remaining SET_ values; opens no device
uv run roboloom run --mock            # operator screen with mock devices
```

Load a configuration and see what the options do:

```python
from roboloom import load_config

cfg = load_config("rakuda2", options=["gravity", "digit"])
print(cfg.options, cfg.repo_id)  # ('digit', 'gravity') local/rakuda2-digit
```

Record episodes from a script (hardware unless `mock=True`):

```python
from roboloom import Session

with Session.launch("rakuda2", options=["gravity"], mock=True) as s:
    s.wait_ready()  # leader aligned with the follower
    for _ in range(3):
        result = s.record(lambda info: f"pick up the cup #{info.index}", seconds=20)
        print(result.index, result.frames, result.warnings)
```

Run a policy (`"module:callable"`, looked up in installed packages, then in
`.roboloom/<robot>/`):

```python
from roboloom import Session

with Session.launch(
    "rakuda2",
    options=["policy"],
    policy="my_lab.policies:load",
    policy_kwargs={"checkpoint": "outputs/act/last"},
) as s:
    s.wait_ready()
    s.record("pick up the cup (eval)", seconds=30)
```

Errors users can act on are `roboloom.ConfigError`, `SetupError`, `HardwareError`,
`SessionError` (all subclasses of `RoboloomError`) and `roboloom.errors.Cancelled`.

Image sensor nodes accept `storage: video | image` (default `video`). Use lossless
`image` for tactile pixel differences; changing it requires a separate dataset output.
See [sensors](references/sensors.md#image-storage).
