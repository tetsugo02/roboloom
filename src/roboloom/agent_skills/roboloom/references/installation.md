# Installation

roboloom is installed from GitHub into the user's own uv project. Python **3.12** only.

## New or existing project

```bash
uv init --python '>=3.12,<3.13' my-robot   # new project
cd my-robot
uv add git+https://github.com/tetsugo02/roboloom.git
uv run roboloom --help
```

For an existing project, first set `project.requires-python = ">=3.12,<3.13"` in
`pyproject.toml`. Selecting a 3.12 interpreter alone does not restrict what uv resolves.

## Extras

| Extra | Adds | Needed for |
| --- | --- | --- |
| (none) | shared runtime: dora, YAML, NumPy, OpenCV, pyserial, CLI/UI | `init`, mock devices, configuration validation, webcam capture |
| `rakuda2` | dynamixel-sdk | Rakuda2 follower and Rakuda-mini leader hardware |
| `piper` | piper_sdk 0.6, pinocchio (`pin`) | PiPER follower and `pose_ik` (in development) |
| `pika` | pysurvive | Pika Sense tracking (in development); cameras and serial use core dependencies |
| `record` | `lerobot[dataset]==0.6.1` | saving episodes (also mock collection that saves) |
| `hardware` | pyrealsense2, sounddevice | RealSense, microphone |
| `digit` | digit-interface 0.2.1 (fork wheel, opencv-python-headless) | DIGIT |
| `ik` | pinocchio (`pin`) | standalone IK without the PiPER SDK; also included in `piper` |
| `policy` | `lerobot==0.6.1` (brings torch) | `roboloom.policy.lerobot:load` |
| `train` | `lerobot[training]==0.6.1` | `lerobot-train` on roboloom datasets |

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra rakuda2 --extra record --extra hardware --extra digit
uv add 'roboloom[rakuda2]'  # after registering the Git source
uv add 'roboloom[piper,pika]'  # PiPER + Pika Sense/Gripper
uv add 'roboloom[policy]'   # once roboloom is already a dependency, extras can be added like this
```

Diffusion / SmolVLA / pi0 policies additionally need `lerobot[diffusion]`,
`lerobot[smolvla]`, `lerobot[pi]`. On a shared GPU machine, check with `labstatus` that a
GPU is free before training or GPU inference.

Hardware hosts also need: USB permissions for the devices, the RealSense system driver and
a USB 3 port; CAN interfaces (PiPER) and tracker udev rules (Pika Sense) need an
administrator (sudo). Robot extras do not install udev rules or configure interfaces.

`pika` installs pysurvive as a wheel built by a fork of libsurvive
(github.com/tetsugo02/libsurvive, branch `roboloom`, GitHub releases), because PyPI has
no Python 3.12 wheel or sdist: CPython 3.12, Linux x86_64 only, libusb bundled, nothing
is compiled at install time. The fork changes only packaging: Gooey/wxPython (a GUI
launcher roboloom does not use) is the optional extra `pysurvive[gui]`. On other
platforms `pika` does not install pysurvive. Only the tracker's udev rules need an
administrator.
Pysurvive is needed only for real Pika Sense tracker poses, not PiPER joint control,
Pika serial/cameras or mock operation. `pika` deliberately installs the complete set;
base, `rakuda2`, `piper`, and `ik` do not install pysurvive. The Python package does not
include `survive-cli`; calibrate from Python with `pysurvive.SimpleContext([..., "--force-calibrate"])`.

## Reproduce, update, pin

`uv add` writes the Git source into `pyproject.toml` and the resolved commit into
`uv.lock`. Commit both; elsewhere run `uv sync --locked`.

```bash
uv lock --upgrade-package roboloom && uv sync --locked                                  # newest commit
uv add git+https://github.com/tetsugo02/roboloom.git --extra record --rev <commit-sha>   # pin a commit
```

Updating roboloom never overwrites `.roboloom/`. It may change this skill: run
`uv run roboloom skills check` afterwards.

The repository's top-level `examples/`, `scripts/` and `.roboloom/` (the `piper-mock` and
`pika-handheld-mock` configurations) are **not** installed with the package. Copy them from
<https://github.com/tetsugo02/roboloom> if needed.

## Check without devices

```python
# main.py – base dependencies only; MockBus; saves nothing
from roboloom import InProcessSession
from roboloom.drivers.mock import MockBus

with InProcessSession.from_components(
    robot="my-mock",
    bus=MockBus(dimension=2),
    joint_names=["j1", "j2"],
    unit="count",
    limits=[
        {"name": "j1", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
        {"name": "j2", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
    ],
    controller=lambda obs: [2048, 2048],
) as session:
    session.start_inference()
    print(session.step())
    session.stop_inference()
```

## This agent skill

```bash
uv run roboloom skills install            # .agents/skills/roboloom and .claude/skills/roboloom
uv run roboloom skills install --agent claude
uv run roboloom skills check              # exit 1 when a copy is missing or outdated
uv run roboloom skills install --force    # replace an outdated copy
uv run roboloom skills path               # the packaged skill, for other agents' folders
npx skills add tetsugo02/roboloom --skill roboloom   # alternative, from GitHub (latest main)
```

Python: `roboloom.agent_skills.install(root=".", targets=("agents", "claude"), force=False)`
and `roboloom.agent_skills.check(...)`.

opencv-python-headless (no GUI; the same package as LeRobot's in `record`) is a core dependency for `opencv_rgb` and V4L2 cameras. `digit` installs digit-interface 0.2.1 from a fork's wheel (github.com/tetsugo02/digit-interface, release `roboloom-1`) whose only change is depending on opencv-python-headless instead of opencv-python; the two distributions write the same `cv2`, so never add opencv-python to the environment. Three-OS webcam driver support does not imply full Windows Session support.
