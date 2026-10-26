# Installation

Use Python **3.12**. The steps below clone the repository and run from its root directory. `robopy` is not a runtime dependency.

## Install with uv

```bash
git clone https://github.com/tetsugo02/roboloom.git
cd roboloom
uv sync --extra record --extra hardware
uv run roboloom --help
```

| Setup | Command | Purpose |
| --- | --- | --- |
| Base | `uv sync` | Configuration loading, CLI, Dynamixel driver |
| Recording | `uv sync --extra record` | Saving to LeRobotDataset, mock collection |
| Hardware collection | `uv sync --extra record --extra hardware` | Recording plus the RealSense and DIGIT SDKs |
| Documentation | `uv sync --group docs` | Zensical preview and build |

The `hardware` extra also includes audio libraries, but this guide covers RealSense and DIGIT. Check USB device access permissions, the RealSense system-side driver, and the USB 3 connection on the machine the hardware is connected to.

## Install with pip

With the same checkout, you can do an editable install into a Python 3.12 virtual environment.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[record,hardware]'
roboloom --help
```

The rest of the guides write `uv run roboloom ...`. In a pip environment, read this as `roboloom ...` in the activated virtual environment.

## Check without devices

In an environment with the `record` extra installed, you can validate the mock configuration. `validate` does not open the hardware.

```bash
uv run roboloom validate examples/mock/experiment.yaml
uv run roboloom run examples/mock/experiment.yaml
```

Enter `start test` → `stop` → `save` → `quit` in the operator screen to save a mock episode. The save location is given by `output` in `examples/mock/experiment.yaml`.

The hardware steps continue in [Rakuda2 Quick start](rakuda2.md).
