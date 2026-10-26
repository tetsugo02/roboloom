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

Add extras for your use case. These are configuration examples for the same dependency.

| Setup | Command | Purpose |
| --- | --- | --- |
| Base | `uv add git+https://github.com/tetsugo02/roboloom.git` | Configuration loading, CLI, Dynamixel driver |
| Recording | `uv add git+https://github.com/tetsugo02/roboloom.git --extra record` | Saving to LeRobotDataset, mock collection |
| Hardware collection | `uv add git+https://github.com/tetsugo02/roboloom.git --extra record --extra hardware` | Recording plus the RealSense and DIGIT SDKs |

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

## Check without devices

With only the base dependencies, save the following as your own `main.py` and run it. It uses `MockBus` and does not save a dataset.

```python
from roboloom import Experiment
from roboloom.drivers.mock import MockBus

with Experiment.from_components(
    robot_id="my-mock",
    robot=MockBus(dimension=2),
    joint_names=["j1", "j2"],
    limits=[
        {"name": "j1", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
        {"name": "j2", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
    ],
    controller=lambda obs: [2048, 2048],
) as experiment:
    experiment.start_inference()
    print(experiment.step())
    experiment.stop_inference()
```

```bash
uv run python main.py
uv run roboloom init rakuda2
```

`init` generates `.roboloom/rakuda2/` in your project from templates shipped in the installed package. It does not open devices. Until you fill in the `SET_...` values, `validate` reports missing configuration. Continue with [Rakuda2 Quick start](rakuda2.md) to use the generated configuration on hardware. Do not use mock values as hardware safety limits.

See [Contribution](../contribution.md) for source changes, tests, and docs builds. The repository's top-level `examples/` and `scripts/` are not installed as package resources when adding the Git dependency.
