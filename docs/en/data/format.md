# Dataset format

With the `record` extra, data is saved as LeRobotDataset 0.6.1. Monotonic-clock timestamps for capture, availability, reception, and command sending are kept distinct for alignment, and missing data is represented by the last valid value and validity flags. `task` is recorded in each frame. Every column with its dtype and shape is listed in [Dataset features](../reference/dataset-features.md).

## What is recorded { #features }

With several followers, `observation.state`, `observation.effort` and `action` are one vector joining all followers in configuration order. Their `names` tell which follower each entry belongs to, as `<follower>.<joint>` (for example `follower.r_arm_sh_pitch1`). The other features are per node and named after it.

| Feature | Content |
| --- | --- |
| `observation.state` | Each follower's joint positions |
| `observation.effort` | The effort of the followers with `record_effort: true`; followers with different units cannot be mixed |
| `observation.<input>` | Each input's own reading, named after the input node (for example `observation.leader`). A joint input such as a leader arm records its joint positions in its own unit, with its joint names (no prefix); a pose input records `x`, `y`, `z`, `qx`, `qy`, `qz`, `qw`, `gripper`, `tracking`, `engaged` |
| `observation.images.<sensor>` and other sensor features | What each sensor records; see the [Sensors](../sensors/index.md) pages |
| `observation.meta.<node>.valid` / `capture_age_ms` / `ready_age_ms` (float32), `seq` / `capture_ns` / `ready_ns` / `receive_ns` (int64) | One set for every recorded node (inputs, followers, sensors): whether the row used a sample of that node, its age since capture and since it became available (ms), its sequence number, and its capture, availability and reception times (monotonic clock, ns) |
| `action` | The first command each follower sent in the row's interval, in the order of `observation.state` |
| `action.valid` | 1 in rows where every follower sent a command |
| `action.clamped` | 1 in rows where any follower limited its command |
| `action.meta.<follower>.valid` / `clamped` / `seq` / `sent_ns` | Each follower's own: command present, limited, command number, send time |

The details are in the [observation](../reference/dataset-features.md#observation), [action](../reference/dataset-features.md#action) and [meta](../reference/dataset-features.md#meta) tables. The unit of every entry of `action` is kept in the dataset's `meta/roboloom.json` ([Dataset metadata](recording.md#metadata)).

## Features that depend on the configuration { #by-configuration }

Which features exist depends on the nodes that ran in the recording.

- `observation.<input>` exists only when that input is in the configuration. The Rakuda2 template's option `policy` removes the leader (`inputs.leader: null`), so its evaluation dataset has no `observation.leader`; `policy_teleop` brings the leader back, so `observation.leader` is there.
- `action.intervention` exists only when a policy controller has `teleop:` ([Teleoperation and interventions](../policy/intervention.md#recording)).
- Joints listed in a policy's `hold` are still in `action`; their entries hold the target the follower keeps ([History, joints left alone, and fresh samples](../policy/custom.md#hold)).
- A policy's `observe` only chooses what the policy is given. Every started sensor is recorded ([Sensor selection](../policy/run.md#sensor-selection)).
- A configuration without followers (a hand-held device, sensors only) has no `action*` features.
- An option that changes the recorded features gets a `dataset` of its own ([Launch options](../reference/configuration/index.md#launch-options)).

## Validity flags { #valid }

| Column | 1 means | 0 means |
| --- | --- | --- |
| `observation.meta.<node>.valid` | The row used a fresh sample of that node | No sample within `max_age_ms`; the values repeat the last valid sample ([Missing data](#missing-data)), and `seq` is -1 |
| `action.valid` | Every follower sent a command in the row's interval | At least one follower sent none |
| `action.meta.<follower>.valid` | That follower sent a command | That follower sent none; its part holds the target it kept |
| `action.clamped`, `action.meta.<follower>.clamped` | The safety checks of a follower (or of that follower) brought the command within the joint limits or the speed limit | The command was not limited |
| `action.intervention` | A person drove the row with the leader (only with `teleop:`) | The policy drove the row |

## Missing data { #missing-data }

- **Stale observations**: a sample older than the node's `max_age_ms` in `nodes/recorder.yaml` is not used: in that row `observation.meta.<node>.valid` is 0 and `seq` is -1, and the features repeat that node's last valid sample (zeros only before its first one). Filling with zeros would pull the minimum and the mean of the statistics to 0. Every input, follower and sensor needs a `max_age_ms` entry ([Recorder configuration](../reference/configuration/recorder.md#recorder)).
- **Rows without a command**: a follower that sent no command fills its part with the target it held (its state's `target`, else its position); filling with zeros would teach a policy a jump to 0. In that row `action.meta.<follower>.valid` and `action.valid` are 0.
- **When a row is final**: once every follower's commands have passed its interval, or after `grace_ms` (default 500 ms).
- **LeRobot training does not look at `valid`**: `lerobot-train` does not select rows by the `*.valid` columns; it counts them as inputs or outputs like any other column. The only rows LeRobot leaves out of the loss are those past the end of an episode (`action_is_pad`). To use valid rows only, select them yourself by `action.valid` or `observation.meta.<node>.valid`. `roboloom check-dataset` shows how many rows are 0 ([Checking and training](check-and-train.md)).
