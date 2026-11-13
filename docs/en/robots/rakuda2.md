# Rakuda2

Rakuda2 has **17 joints**: 3 torso/head joints, plus 6 arm joints and 1 gripper joint on each of the left and right sides. Joint values are raw Dynamixel position counts, and current is in mA.

The follower is `type: rakuda2_follower` and the operator input, in the `leader` role, is the Rakuda-mini arm (`type: rakuda_mini`). The leader and follower use separate Dynamixel buses, each owned exclusively by its node. Create the configuration with `roboloom init rakuda2`.

## Supported controllers

The current operation guide covers the [Leader](../controllers/leader.md). Joint positions are read via `inputs.leader`, and a `type: joint` controller converts them for the follower.

- Standard leader: the arms, torso, and head have torque off; the trigger is controlled as a spring.
- Leader with gravity compensation: the left and right arms are controlled with `gravity_comp`, using the identified gravity model, range of motion, and tuning values.
- Selected leader joints can be locked at their startup pose with `position`. Configure torso-yaw compensation for the neck camera through `couplings` in the `joint` controller. Both standard and gravity-compensated leaders can use these options; they are disabled by default. See the [examples and limitations](../controllers/leader.md). The combination has been verified only in mock environments.
- Align the leader and follower before starting. While in `aligning`, start is refused and the joint differences are shown as a warning. You can retry after aligning.

## Supported sensors

| Sensor | Node name | Config | Recorded values |
| --- | --- | --- | --- |
| [RealSense](../sensors/realsense.md) | `camera` | `nodes/camera.yaml` | RGB image (depth is not captured) |
| [DIGIT](../sensors/digit.md) | `digit_left`, `digit_right` | `nodes/digit_left.yaml`, `nodes/digit_right.yaml` | Left and right tactile RGB images |

Set the sensor serial numbers to match the hardware. Sensor names are also used as feature names in the dataset.

## Observation and action

The recorded dataset and the policy's inputs and outputs share the same order and units.

| Name | Entries | Unit |
| --- | --- | --- |
| `observation.state`, `action` | 17 (`follower.torso_yaw`, `follower.head_yaw`, `follower.head_pitch`, the right arm `follower.r_arm_sh_pitch1` … `follower.r_arm_grip`, the left arm `follower.l_arm_sh_pitch1` … `follower.l_arm_grip`) | Dynamixel position counts |
| `observation.effort` | 17 (same order; `record_effort: true` in the template) | mA (current) |
| `observation.leader` | 17 (the leader's joint positions, same order; names without a prefix, `torso_yaw` … `l_arm_grip`; not recorded with option `policy`, which has no leader) | Dynamixel position counts |
| `observation.images.camera` | 480×640×3 (RGB) | [storage](../reference/configuration.md#image-storage) |
| `observation.images.digit_left`, `observation.images.digit_right` | 320×240×3 (RGB; option `digit`) | [storage](../reference/configuration.md#image-storage) |
| `observation.meta.<node>.valid`, `capture_age_ms`, `ready_age_ms` | 1 each (float32), for every recorded node: `leader`, `follower`, `camera`, and with `digit` also `digit_left`, `digit_right` | `valid` 0/1, ages in ms |
| `observation.meta.<node>.seq`, `capture_ns`, `ready_ns`, `receive_ns` | 1 each (int64), same nodes | sequence number, monotonic-clock ns |
| `action.valid`, `action.clamped` | 1 each (float32) | 0/1 |
| `action.meta.follower.valid`, `clamped`, `seq`, `sent_ns` | 1 each (`valid`, `clamped` float32; `seq`, `sent_ns` int64) | 0/1, command number, monotonic-clock ns |

- What `observation.leader`, `observation.meta.<node>.*`, `action.valid`, `action.clamped` and `action.meta.follower.*` mean, how missing samples are recorded, and what `action` holds in rows without a command are described in "Recording and resuming" of [Configuration](../reference/configuration.md#recording-and-resuming); they are the same for every robot.
- The policy (option `policy`) observes joint state and `camera` by default. Select sensors with `observe` in `nodes/policy.yaml` (`[]` for joint state only). `infer` returns targets for the 17 joints in counts: one step `[17]` or a chunk `[H, 17]`.
- `max_speed` is in counts/s (`{follower: 1024}` in the template).
- The template's default policy `roboloom.policy:hold` keeps the arms in place. How to write a policy is in [Driving with a policy](../controllers/policy.md).

## Launch options and combinations

There is one configuration, `.roboloom/rakuda2/config.yaml`. With no option enabled it uses the standard leader, the `joint` controller, and the RealSense. The template has the following launch options (all disabled by default). See [CLI](../reference/cli.md) for choosing them and "Launch options" in [Configuration](../reference/configuration.md) for the rules.

| Option | What it does | Requires / conflicts | Dataset name |
| --- | --- | --- | --- |
| `digit` | Records the left and right DIGIT | | Appends `-digit` |
| `gravity` | Gravity-compensates the leader's left and right arms (`nodes/leader_gravity.yaml`) | | Unchanged |
| `bilateral` | Force feedback (not verified on hardware); replaces the leader, controller, and robot and adds the estimator `effort` | Requires `gravity` | Appends `-bilateral` |
| `policy` | A learned policy drives the follower; removes the leader and controller and adds `controllers.policy`; `roboloom infer` enables it automatically | Conflicts with `gravity` | Appends `-eval` |

| Enabled options | Leader | Sensors | `repo_id` |
| --- | --- | --- | --- |
| none | Standard | RealSense | `local/rakuda2` |
| `digit` | Standard | RealSense + left/right DIGIT | `local/rakuda2-digit` |
| `gravity` | With gravity compensation | RealSense | `local/rakuda2` |
| `gravity`, `digit` | With gravity compensation | RealSense + left/right DIGIT | `local/rakuda2-digit` |
| `gravity`, `bilateral` | With gravity compensation + force feedback (not verified on hardware) | RealSense | `local/rakuda2-bilateral` |
| `policy` | None (policy) | RealSense | `local/rakuda2-eval` |
| `digit`, `policy` | None (policy) | RealSense + left/right DIGIT | `local/rakuda2-digit-eval` |

Limitations:

- Use `gravity` only after the measurement steps of the [Quick start](../quick-start/rakuda2.md) (`calibrate-joints`, `measure-travel`, `identify-gravity`, `tune-gravity`). Loading is refused while measured values are still `SET_...`.
- Enabling or disabling `gravity` changes the leader's Operating Mode. On a hardware launch from a terminal, the CLI shows the EEPROM differences and writes them after confirmation.
- `policy` works without DIGIT. To pass DIGIT images to the policy, enable `digit` and change `observe` in `nodes/policy.yaml` to `[camera, digit_left, digit_right]`. Enabling `digit` alone does not change the policy inputs. Match the inputs used for training. Loading a LeRobot checkpoint that needs DIGIT without DIGIT is refused before starting.
- For a policy using joint state only, set `observe: []`. To avoid opening sensors, also remove their nodes from `sensors` in `config.yaml`.
- `policy` does not use the leader, so it cannot be combined with `gravity`, nor with `bilateral`, which requires `gravity`.
- `gravity` does not change the dataset name because it records the same features as the standard leader; episodes with the standard and the gravity-compensated leader go into the same dataset.
- Because the image features change, `digit` separates the dataset; DIGIT episodes are not appended to an existing RealSense-only dataset.

## Bilateral (not verified on hardware)

The option `bilateral` is the combination that returns the external force on the follower to the leader. It has not been verified on hardware; only the mock tests pass.

| Node | Configuration | Contents |
| --- | --- | --- |
| robot | `nodes/follower_bilateral.yaml` | Runs the arms in current-based position control (Operating Mode 5, `current_position`). `goal_current_mA` is the force limit on contact. Choose `SET_FOLLOWER_ARM_GOAL_CURRENT_mA` and write the Mode and Current Limit with `roboloom commission` |
| leader | `nodes/leader_bilateral.yaml` | The gravity-compensated leader with `feedback:` added to the arm groups |
| controller | `nodes/controller_bilateral.yaml` | `feedback:` names the estimator and the joints that receive feedback (initially the right elbow only, with a small gain) |
| estimator | `nodes/effort.yaml` | Estimator of the follower's external effort (`model_residual`). Uses gravity models identified on the follower, `calibration/effort_gravity_<side>.yaml`. The contact thresholds are provisional values, not measured |

Limitations:

- Start is refused unless `goal_current_mA` is at most the EEPROM `current_limit`.
- After the motors are rewritten to Mode 5, the standard `nodes/follower.yaml` (Mode 3) is refused by the startup check. To go back, write the values back with `commission follower`; on a hardware launch from a terminal, the CLI shows the differences before launching and writes them back after confirmation.
- Every command with `bilateral` enabled (such as `roboloom commission follower --with bilateral`) loads the whole configuration, so it stops while the follower gravity models (`calibration/effort_gravity_<side>.yaml`) are missing. Identification works before the Mode is changed (still Mode 3), so identify first, then `commission`.
- The configuration keys are under "Force feedback" in [Configuration](../reference/configuration.md).

## Checks before launch

Verify ports, motor IDs, models, EEPROM, joint ranges, and speed/current limits on the hardware. The template has `torque` set to `true`, so if you want to check the pipeline the first time without moving the follower, **change `nodes/follower.yaml` to `torque: false` before launch**. Leader-side control is independent; the trigger and gravity compensation are energized.

The control rate is 120 Hz in the templates. For its conditions and how to lower it, see [Configuration](../reference/configuration.md#control-rate).

For the steps from setup to data collection, see [Rakuda2 Quick start](../quick-start/rakuda2.md); for the meaning of the control values, see [Gravity tuning](../reference/gravity-tuning.md).

## Sensor selection

`load_config(..., sensors=[...], observe=[...])` and
`Session.launch(..., sensors=[...], observe=[...])` select sensors independently
from policy observations. None keeps configuration defaults; [] selects none.
Follower state is always observed. When passing RobotConfig, select in load_config;
Session.launch rejects additional selection arguments.

```python
with Session.launch(
    "rakuda2",
    options=["policy"],
    sensors=["camera", "audio"],
    observe=["camera"],
    policy="my_lab.policies:load",
) as session:
    session.wait_ready()
    session.record("pick", seconds=20)
```

`--sensors camera,audio --observe camera` makes the same CLI selection;
`--sensors "" --observe ""` selects none. The launcher provides separate
sensor and observation checkboxes and remembers selections.
Unselected sensor YAML files are not loaded. Observing an inactive sensor fails.
Sensors introduced by options can also be selected individually, including either DIGIT.
An optional sensor uses `{file: nodes/audio.yaml, default: false}`; string paths
remain enabled by default. Options apply first. Recording includes every active sensor,
even those omitted from observe. See [Audio](../sensors/audio.md).
