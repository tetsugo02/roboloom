# Dataset features

| Detail | Description |
| --- | --- |
| — | The columns (features) roboloom writes to a LeRobotDataset 0.7.0. Which columns exist depends on the configuration's followers, inputs, sensors and recorded estimators, and on the enabled options. `roboloom.recording.features(cfg)` lists them for a configuration (see [Recording](python-api/recording.md#features)). How rows are assigned and how missing data is handled is in [Data format](../data/format.md). |
| — | `<follower>`, `<input>`, `<sensor>`, `<estimator>` and `<source>` are node names in the configuration (`follower`, `leader`, `camera`, `digit_left` and so on in the Rakuda2 template). |
| — | `<source>` is every recorded node (inputs, followers, sensors, estimators with `record: true`). |
| — | A column shared by several nodes (`observation.state` and others) joins their values in configuration order. Its `names` tell which entry belongs to which node (`follower.r_arm_sh_pitch1`). |
| — | Shapes are per row. |

## Observation { #observation }

| Column | dtype | shape | Present when | Meaning |
| --- | --- | --- | --- | --- |
| `observation.state` | float32 | (joints of every follower,) | there are followers | Each follower's joint positions, in its unit. `names` are `<follower>.<joint>` |
| `observation.effort` | float32 | (joints of the followers with `record_effort`,) | a follower has `record_effort: true` | Joint current or torque, in the model's unit (mA for Rakuda2 and Pika, N·m for PiPER). One column cannot mix models with different units |
| `observation.<input>` | float32 | (joints,) | there is a joint input (a leader and so on) | The input device's joint positions; `names` are the joint names. Option `policy` removes the leader, so the column is absent; `policy_teleop` brings the leader back, so the column is present |
| `observation.<input>` <span class="status status--dev">In development</span> | float32 | (10,) | there is a pose input (Pika Sense) | `x`, `y`, `z` (m), `qx`, `qy`, `qz`, `qw`, `gripper` (rad; 0 for devices without one), `tracking` (1/0), `engaged` (1/0) |
| `observation.images.<sensor>` | `video` or `image` | (height, width, 3) | a camera or tactile image sensor (RealSense, DIGIT, ...) | RGB image. The dtype is the sensor's `storage` (default `video`; `image` is <span class="status status--mock">Mock only</span>). `names` are `height`, `width`, `channels` |
| `observation.audio.<sensor>` <span class="status status--dev">In development</span> | int16 | (`sample_rate` / `dataset_fps`,) | `type: pcm_mono` | One row of PCM |
| `observation.audio.<sensor>` <span class="status status--dev">In development</span> | float32 | (`n_mels`, 1 + `sample_rate`·`window_seconds` // `hop_length`) | `type: mel_mono` | Log mel power of the last `window_seconds` (low frequencies first) |
| `observation.effort_ext` <span class="status status--mock">Mock only</span> | float32 | (estimated joints,) | an estimator with `record: true` | External effort (the estimator's residual, negated), in the estimator's unit. `names` are `<follower>.<joint>` |
| `observation.effort_ext.valid` <span class="status status--mock">Mock only</span> | float32 | (number of estimators,) | an estimator with `record: true` | 1 when that estimator's estimate is valid |
| `observation.contact` <span class="status status--mock">Mock only</span> | float32 | (number of estimators,) | an estimator with `record: true` | 1 when it detects contact |
| `task` | string (LeRobot turns it into `task_index`) | — | always | The episode's task |
| Detail | Description |
| --- | --- |
| — | A row without a usable sample repeats that node's last valid value (zeros before its first sample), and `observation.meta.<source>.valid` is 0 ([Missing data](../data/format.md#missing-data)). |
| — | A policy receives its observation with the same names and shapes (without `observation.meta`; [Observations](../policy/custom.md#observations)). |

## Action { #action }

| Detail | Description |
| --- | --- |
| — | A configuration without followers (a hand-held device) has no columns starting with `action`. |

| Column | dtype | shape | Present when | Meaning |
| --- | --- | --- | --- | --- |
| `action` | float32 | (joints of every follower,) | there are followers | The first command each follower sent in the row's interval [t_k, t_{k+1}), in the order and units of `observation.state`. A follower that sent none fills its part with the target it held (else its position). Joints listed in a policy's `hold` are there too; explicitly claimed hooks can change their held target |
| `action.valid` | float32 | (1,) | there are followers | 1 when every follower sent a command in the row |
| `action.clamped` | float32 | (1,) | there are followers | 1 when a limit cut down any follower's command |
| `action.intervention` | float32 | (1,) | the policy has `teleop:` (option `policy_teleop`) | 1 when a person drove the row with the leader ([teleoperation and interventions](../policy/intervention.md#teleop)) |
| `action.filtered` <span class="status status--mock">Mock only</span> | float32 | (1,) | a policy YAML `hooks:` entry has nonempty `writes` (factory or `from: policy`) | 1 if any valid command in any follower’s row interval was changed by a hook, before speed/safety limits; OR over all commands, including policy teleop. No column without writing claims |

## Metadata { #meta }

| Detail | Description |
| --- | --- |
| — | Each node's times and validity. Times are in `time.monotonic_ns()` time. |

| Column | dtype | shape | Present when | Meaning |
| --- | --- | --- | --- | --- |
| `observation.meta.<source>.valid` | float32 | (1,) | per recorded node | 1 when a sample captured within `max_age_ms` of the row time t_k is available (one sample may serve several rows); at 0 the row repeats the last valid value |
| `observation.meta.<source>.capture_age_ms` | float32 | (1,) | per recorded node | Time since the sample was captured, seen from the row time t_k (ms); 0 without a sample |
| `observation.meta.<source>.ready_age_ms` | float32 | (1,) | per recorded node | Time since the sample became ready, seen from t_k (ms); 0 without a sample |
| `observation.meta.<source>.seq` | int64 | (1,) | per recorded node | The sample's sequence number; −1 without a sample |
| `observation.meta.<source>.capture_ns` | int64 | (1,) | per recorded node | When the sample was captured; 0 without a sample |
| `observation.meta.<source>.ready_ns` | int64 | (1,) | per recorded node | When the sample became ready; 0 without a sample |
| `observation.meta.<source>.receive_ns` | int64 | (1,) | per recorded node | When the recorder received it; 0 without a sample |
| `action.meta.<follower>.valid` | float32 | (1,) | per follower | 1 when that follower sent a command in the row's interval |
| `action.meta.<follower>.clamped` | float32 | (1,) | per follower | 1 when a limit cut that command down |
| `action.meta.<follower>.seq` | int64 | (1,) | per follower | The command's sequence number; −1 without one |
| `action.meta.<follower>.sent_ns` | int64 | (1,) | per follower | When the command was sent; 0 without one |
| Detail | Description |
| --- | --- |
| — | LeRobot adds its own columns too. |

| Column | dtype | shape | Meaning |
| --- | --- | --- | --- |
| `timestamp` | float32 | (1,) | Time since the episode's start (s) |
| `frame_index` | int64 | (1,) | Row number within the episode |
| `episode_index` | int64 | (1,) | Episode number |
| `index` | int64 | (1,) | Row number in the whole dataset |
| `task_index` | int64 | (1,) | The task's number |

## In training { #training }

| Detail | Description |
| --- | --- |
| — | LeRobot gives `*.valid` columns no special meaning: rows whose `valid` is 0 are trained on like any other. To leave them out, see [Checking the data and training](../data/check-and-train.md#training) and [valid](../data/format.md#valid). |
| — | LeRobot puts every column starting with `observation.` into the policy configuration as an observation feature and every column starting with `action` as an action feature. The models of policies such as ACT, however, read `observation.state`, `observation.environment_state` and the images: `observation.meta.*`, `observation.<input>` and `observation.effort` are not model inputs, even when the dataset has them. |

## Rakuda2 example { #rakuda2-example }

| Detail | Description |
| --- | --- |
| — | The columns that change with each option in the Rakuda2 template (`roboloom init rakuda2`). |

| Option | Columns added | Columns removed |
| --- | --- | --- |
| none (teleop collection) | `observation.state`, `observation.effort`, `observation.leader`, `observation.images.camera`, `action`, `action.valid`, `action.clamped`, `action.meta.follower.*`, `observation.meta.{leader,follower,camera}.*` | — |
| `digit` | `observation.images.digit_left`, `observation.images.digit_right`, and their `observation.meta.*` | — |
| `policy` | — | `observation.leader`, `observation.meta.leader.*` |
| `policy_teleop` | `observation.leader`, `observation.meta.leader.*`, `action.intervention` | — |
| `pika` <span class="status status--dev">In development</span> | `observation.right_sense`, `observation.left_sense`, and their `observation.meta.*` | `observation.leader`, `observation.meta.leader.*` |
| `--sensors camera,audio` <span class="status status--dev">In development</span> | `observation.audio.audio`, `observation.meta.audio.*` | — |
| `bilateral` <span class="status status--mock">Mock only</span> | `observation.effort_ext`, `observation.effort_ext.valid`, `observation.contact`, `observation.meta.effort.*` | — |
