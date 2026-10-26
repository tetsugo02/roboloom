# Configuration

## Specifying an experiment

`roboloom init rakuda2` creates experiment, node, and calibration YAML in `.roboloom/rakuda2/`. It does not overwrite an existing directory. The experiment name `rakuda2` refers to `experiment.yaml`, and `rakuda2/experiment_gravity` refers to `experiment_gravity.yaml`. You can also specify a file path.

## Experiment YAML

```yaml
robot_id: rakuda2
repo_id: local/rakuda2
output: datasets/rakuda2
mode: hardware
dataset_fps: 15
inputs:
  leader: nodes/leader.yaml
controllers:
  controller: nodes/controller.yaml
robots:
  robot: nodes/robot.yaml
sensors:
  camera: nodes/camera.yaml
  digit_left: nodes/digit_left.yaml
  digit_right: nodes/digit_right.yaml
recorder: nodes/recorder.yaml
session: nodes/session.yaml
```

Node YAML paths and `output` are relative to the experiment file's directory. The output location above is `.roboloom/rakuda2/datasets/rakuda2`. Node names are used as dora IDs and as dataset feature names. Currently, each experiment has one robot and one corresponding controller.

Each node's `type` selects the implementation. `SET_...` are robot-specific unset values; execution is refused if any remain in a referenced configuration. `validate` checks the consistency of the configuration and dataflow without opening devices. It does not check that EEPROM matches the hardware, image capture, or stopping behavior.

## Joint locking and compensation

The leader node's `control` selects a law per joint group, such as `free` (torque off), `position` (holds the torque-enable pose on a leader), `spring`, or `gravity_comp`. Specify every joint exactly once. The `joint` controller's `couplings` (default `[]`) is a list of `{joint, source, scale, reference}` entries that add another follower joint's measured displacement from `reference` to a target. These settings are independent. See the [Leader configuration examples](../controllers/leader.md).

## Recording and resuming

With the `record` extra, data is saved as LeRobotDataset 0.6.1. Monotonic-clock timestamps for capture, availability, reception, and command sending are kept distinct for alignment, and missing data is represented by zero values and validity flags. `task` is recorded in each frame.

You can append further episodes to the same dataset. On resume, FPS and feature compatibility are checked. If you change the sensor configuration, use a separate `repo_id` / `output`.

Thresholds for quality warnings can be set with `max_missing_rate`, `min_action_valid_rate`, and `max_interval_ms` in `recorder.quality`. Check the metrics and warnings in the save result.

## Managing logs and configuration

Logs are placed in `logs/<experiment name>-<time>/` next to the experiment file. Manage YAML configuration, gravity models, ranges of motion, and tuning values with Git; raw data `*.npz`, logs, datasets, and FIFOs are excluded by the generated `.roboloom/.gitignore`.

API details are in [Python API](python-api.md), and commands are in [CLI](cli.md).
