# First run without devices

<span class="status status--mock">Mock only</span>

- **Goal**: start, record, save and check a dataset with mock devices.
- **Prerequisites**: a clone of the roboloom repository, Python 3.12–3.14 and uv. `examples/` exists only in the clone; it is not in the installed package.
- **Time**: 15 minutes.
- **Result**: `datasets/rakuda-mock` holds a LeRobotDataset with two episodes, and `check-dataset` reports `problems: none`.

`examples/mock/config.yaml` is a mock Rakuda (leader and follower) with a camera, left and right DIGIT, and audio. It uses no hardware values, so it runs without measuring anything.

## 1. Set up the environment

```bash
git clone https://github.com/tetsugo02/roboloom.git
cd roboloom
uv sync --extra rakuda2 --extra record
```

## 2. Validate the configuration

```bash
uv run roboloom validate examples/mock/config.yaml
```

`Valid: ... (9 nodes; options: none; dataset: local/rakuda-mock; ...)` means the configuration and the dataflow are put together. `validate` opens no devices.

## 3. Run it in the operator screen

```bash
uv run roboloom run examples/mock/config.yaml
```

1. In the launcher, choose the operation `run` and press Launch (Ctrl-S).
2. Look at the state of every node and the sensors' capture rates. Wait until the controller is `following`.
3. In the command line (Ctrl-L), enter `start mock demo`, and a few seconds later `stop` and `save`.
4. Finish with `quit`.

The operations are explained in [run operations](../reference/cli.md#run-operations), the keys in [Operator screen](../reference/operator-screen.md).

## 4. Record episodes of a fixed length

```bash
uv run roboloom record examples/mock/config.yaml --task "mock demo" --seconds 5 --episodes 2 --plain
```

`--plain` records without key input. `saved episode 0: 'mock demo', ... frames` appears twice. The output is `datasets/rakuda-mock` (`output` is relative to the configuration).

## 5. Check the recording

```bash
uv run roboloom check-dataset examples/mock/config.yaml
```

| Output | What to look at |
| --- | --- |
| `episodes`, `frames`, `fps` | the episodes and rows; `fps` is the configuration's `dataset_fps` (10) |
| `problems` | `none` means no broken files |
| `notes` | the share of rows where a `*.valid` is 0; a little shows up even with mock devices, around the first rows |

What is checked is listed in [Checking and training](../data/check-and-train.md#check-dataset).

## Next

- Write a policy and run it on mock devices: [Running your own policy](custom-policy.md)
- Add your own robot: [Adding your own robot](own-robot.md)
- Start on the real Rakuda2: [Rakuda2: configuration and read check](rakuda2-setup.md)
