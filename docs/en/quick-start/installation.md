# Installation

Use Python **3.12**, uv, and Git. Add roboloom from GitHub as a dependency of your own project. Run the commands below from your project root.

## Install with uv

To create a new project:

```bash
uv init --python '>=3.12,<3.13' my-robot
cd my-robot
uv add git+https://github.com/tetsugo02/roboloom.git
uv run roboloom --help
```

For an existing project, start with `uv add` from its root. First set `project.requires-python` in `pyproject.toml` to `">=3.12,<3.13"`. Selecting a Python 3.12 environment alone does not limit the Python compatibility range that uv resolves.

The base install contains the shared runtime (dora, YAML, NumPy, OpenCV, serial communication, and the UI). Choose robot extras separately; recording and RealSense / DIGIT remain independent extras. These are configuration examples for the same Git dependency.

| Setup | Command | Purpose |
| --- | --- | --- |
| Base | `uv add git+https://github.com/tetsugo02/roboloom.git` | Configuration loading, CLI, mock devices |
| Rakuda2 | `uv add git+https://github.com/tetsugo02/roboloom.git --extra rakuda2` | Dynamixel SDK for the follower and Rakuda-mini leader |
| PiPER + Pika | `uv add git+https://github.com/tetsugo02/roboloom.git --extra piper --extra pika` | PiPER SDK, IK, Pika tracking and wrist cameras (in development, hardware unverified) |
| Recording | `uv add git+https://github.com/tetsugo02/roboloom.git --extra record` | Saving to LeRobotDataset, mock collection |
| Rakuda2 hardware collection | `uv add git+https://github.com/tetsugo02/roboloom.git --extra rakuda2 --extra record --extra hardware` | Rakuda2, recording, RealSense and DIGIT SDKs |

Once the Git source is registered, extras can also be added by package name. Quote the brackets in shells such as zsh:

```bash
uv add 'roboloom[rakuda2]'
uv add 'roboloom[piper,pika]'
uv add 'roboloom[piper,pika,record]'
```

`rakuda2` adds `dynamixel-sdk`; `piper` adds `piper_sdk` and Pinocchio (`pin`) for `pose_ik`; `pika` adds `pysurvive`. OpenCV and `pyserial` are core dependencies shared by camera processing and serial devices. The standalone `ik` extra remains available for IK without the PiPER SDK. In a repository checkout, select the same extras with `uv sync --extra rakuda2` or `uv sync --extra piper --extra pika`.

`pysurvive` is needed only for real Pika Sense tracker poses, not for PiPER joint control, Pika serial commands/cameras, or mocks. The `pika` extra installs the complete Pika dependency set. [PyPI](https://pypi.org/project/pysurvive/) has no Python 3.12 wheel or source distribution, so it uses a wheel built by a [fork of libsurvive](https://github.com/tetsugo02/libsurvive/tree/roboloom) ([releases](https://github.com/tetsugo02/libsurvive/releases); CPython 3.12, Linux x86_64, libusb bundled). Nothing is built at install time, so no compiler or libusb development files are needed. The fork changes only the Python packaging: upstream's required Gooey/wxPython (the launcher of a GUI roboloom does not use) becomes the optional extra `pysurvive[gui]`. On Linux other than x86_64 and on other systems, the `pika` extra does not install pysurvive. The extra does not change OS settings, install the tracker's udev rules (`81-vive.rules`), or configure CAN; ask an administrator for the udev rules.

The `hardware` extra also includes audio libraries, but this guide covers RealSense and DIGIT. Check USB device access permissions, the RealSense system-side driver, and the USB 3 connection on the machine the hardware is connected to.

`uv add` registers the dependency and Git source in your `pyproject.toml` and records the resolved commit in `uv.lock`. Commit both files and reproduce the environment elsewhere with `uv sync --locked`. See [uv's Git dependency documentation](https://docs.astral.sh/uv/concepts/projects/dependencies/#git) for details.

## Updating and pinning a commit

To update to a newer commit on the default branch:

```bash
uv lock --upgrade-package roboloom
uv sync --locked
```

To use a specific commit, replace `<commit-sha>` with an actual commit SHA. This example includes the recording extra.

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra record --rev <commit-sha>
```

Updating the package does not overwrite existing configuration under `.roboloom/`.

## Use with coding agents

roboloom ships an [Agent Skill](https://agentskills.io) (`SKILL.md` and reference pages) that tells coding agents such as Claude Code and Codex how to use roboloom from your project: installation and extras, `.roboloom/<robot>/`, `Session`, `roboloom.setup`, the CLI, policies, and the safety rules (for example, not to open hardware without your request). Copy the skill of the installed version into your project:

```bash
uv run roboloom skills install            # .agents/skills/roboloom (Codex and others) and .claude/skills/roboloom (Claude Code)
uv run roboloom skills install --agent claude
```

Commit the copied directories with your project. After updating roboloom, `uv run roboloom skills check` reports a copy that no longer matches (exit status 1); replace it with `uv run roboloom skills install --force`. Only the `roboloom/` skill directory is replaced; other skills are left as they are. For an agent that reads another directory, copy the directory printed by `uv run roboloom skills path`. The [skills CLI](https://github.com/vercel-labs/skills) can also install it from GitHub (the latest default branch, which may differ from your locked version): `npx skills add tetsugo02/roboloom --skill roboloom`.

## Check without devices

With only the base dependencies, save the following as your own `main.py` and run it. It uses `MockBus` and does not save a dataset.

```python
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

```bash
uv run python main.py
uv run roboloom init rakuda2
```

`init` generates `.roboloom/rakuda2/` in your project from templates shipped in the installed package. It does not open devices. Until you fill in the `SET_...` values, `validate` reports missing configuration. Continue with [Rakuda2 Quick start](rakuda2.md) to use the generated configuration on hardware. Do not use mock values as hardware safety limits.

See [Contribution](../contribution.md) for source changes, tests, and docs builds. The repository's top-level `examples/` and `scripts/` are not installed as package resources when adding the Git dependency.

## Web camera

```bash
uv add git+https://github.com/tetsugo02/roboloom.git
```

See [Web camera](../sensors/webcam.md). Three-OS support applies to the sensor driver, not the full Windows Session runtime.
