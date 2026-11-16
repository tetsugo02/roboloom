# Control laws (control)

`control:` in the node YAML of a leader (`rakuda_mini`) or a follower (`rakuda2_follower`) chooses a control law per joint group. The same laws serve leaders and followers. This page lists the keys of each law, and the keys of a follower's `limits` and a controller's `home`. For how to use them, see the [Leader configuration examples](../../controllers/leader.md) and [Gravity compensation](../../explanation/gravity-compensation.md).

## Keys of every group { #common }

`control:` is a list of groups. Every joint belongs to exactly one group, and group names are unique. A group takes only the keys its law reads; any other key is refused at load.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `group` | text | required | — | Group name; [`extends`](index.md#extends) lays a group over the base's group of the same name |
| `law` | text | required | — | One of `free`, `position`, `current_position`, `spring`, `gravity_comp`, `impedance` |
| `joints` | list of text | required | — | The group's joints |
| `feedback` | mapping | — | — | Takes force feedback ([below](#feedback)); current-mode laws only (`gravity_comp`, `impedance`) <span class="status status--mock">Mock only</span> |

A law fixes its operating mode (the Dynamixel Operating Mode). On Rakuda2 a `registers.operating_mode` in the YAML that contradicts it is refused.

| `law` | Operating mode | Current mode |
| --- | --- | --- |
| `free` | none (torque off) | — |
| `position` | position | — |
| `current_position` | current-based position | — |
| `spring` | current-based position | — |
| `gravity_comp` | current | yes |
| `impedance` | current | yes |

On hardware, a node with a current-mode group needs `bus_watchdog_ms`.

## free { #free }

Torque off, for a leader joint moved by hand. No keys besides the common ones.

## position { #position }

Moves to the target; without a target it keeps the last goal. On a leader it holds the pose it had when torque turned on (a locked joint). No keys besides the common ones.

## current_position { #current-position }

Current-based position control: the goal current is the torque limit. With `target` it becomes a spring back to that position.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `goal_current_mA` | number or one per joint | required | mA | Goal current (the torque limit); on hardware at most the EEPROM `registers.current_limit` |
| `target` | number or one per joint | — | joint unit | A fixed target; when set, the input's target is not used |

## spring { #spring }

A return spring for a hand-operated joint, such as a leader's gripper trigger. The joint is held at `rest` in current-based position mode; pushing it away meets a force that grows with the displacement, capped by `goal_current_mA`, so the operator can always overpower it.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `rest` | number or one per joint | required | joint unit | Position it returns to |
| `goal_current_mA` | number or one per joint | required | mA | Cap of the returning force; on hardware at most the EEPROM `registers.current_limit` |

## Keys of current-mode laws { #current-laws }

The keys `gravity_comp` and `impedance` read. The output ramps in over `ramp_s` and is clipped per joint to `max_current_mA`. A joint that moves too fast or leaves its range counts as a runaway, and the node goes limp.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `max_current_mA` | number or one per joint | required | mA | Cap of the output current |
| `max_velocity` | number | required | count/s | A joint faster than this is a runaway |
| `range` | list of `[min, max]` per joint, or a file path | required | count | Range of motion; a path names the file `roboloom measure-travel` writes |
| `range_margin` | number | `100` | count | Margin outside `range` that is not yet a runaway |
| `barrier_mA_per_count` | number | `0.5` | mA/count | Current that pushes back outside `range` |
| `gravity_model` | path | — | — | Gravity model (output of `roboloom identify-gravity`), relative to the node file's directory |
| `gravity_gain` | number or one per joint | `1.0` with a gravity model, else `0.0` | — | Gain of the gravity term |
| `tuning` | path | — | — | Tuned values written by `roboloom tune-gravity` (`gravity_gain`, `hold_mA`, `hold_kp`); setting those keys inline as well is refused |
| `kd` | number or one per joint | `0.0` | mA/(count/s) | Damping |
| `ramp_s` | number | `1.0` | s | Time from torque on to the full output |
| `homing` | `{kp_mA_per_count, max_mA}` | — | mA/count, mA | The spring that pulls the joint along a `home` move; required on a leader's current-mode groups when its controller has [`home`](#home) |

## gravity_comp { #gravity-comp }

A hand-guided joint that does not fall: current = `gain × g(q) − kd × velocity` plus the range barrier. With `hold_mA` above 0, a spring of `hold_kp` pulls the joint to an anchor, never harder than `hold_mA`; pushed harder, the anchor slides along with the hand (it acts like friction).

Besides the [keys of current-mode laws](#current-laws) it reads the following. `gravity_model` is required.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `hold_mA` | number or one per joint | `0.0` | mA | Cap of the holding force; 0 does not hold |
| `hold_kp` | number | `1.0` | mA/count | Stiffness of the holding spring |

## impedance <span class="status status--mock">Mock only</span> { #impedance }

Joint impedance around the target: `kp (q* − q) − kd × velocity + gain × g(q)`. It is not validated on hardware, so on hardware it needs `allow_unvalidated: true`.

Besides the [keys of current-mode laws](#current-laws) it reads the following.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `kp` | number or one per joint | required | mA/count | Stiffness |
| `allow_unvalidated` | boolean | `false` | — | `true` lets it start on hardware |

## Taking force feedback (feedback) <span class="status status--mock">Mock only</span> { #feedback }

`feedback:` on a leader's current-mode group (`gravity_comp`, `impedance`) makes its joints take the feedback a controller sends. Position-mode groups and `free` cannot have it. For the path and the controller's side see the [controller's `feedback`](controllers.md#feedback).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `max_mA` | number or one per joint | required | mA | Limit of the feedback alone |
| `ramp_s` | number | `0.3` | s | Time the gate takes to open or close |
| `kd` | number or one per joint | `0.0` | mA/(count/s) | Damping added while the feedback is on |

```yaml
- group: right_arm
  law: gravity_comp
  # ...
  feedback:
    max_mA: 20     # limit of the feedback alone (a per-joint list also works)
    ramp_s: 0.3    # time the gate takes to open or close (default 0.3)
    kd: 0.0        # damping added while the feedback is on, mA/(count/s) (default 0)
```

Every tick, the leader adds the following to the law's output, then clips the sum at `max_current_mA`.

```text
gate × (clip(received current, ±max_mA) − kd × velocity)
```

`gate` is a value from 0 to 1. It moves toward 1 over `ramp_s` while the controller asks for the feedback and the message is within its deadline (`deadline_ms`), and toward 0 otherwise. It never jumps. Estop, release, quit, going limp, and a detected runaway set it to 0 at once. Joints that take feedback are checked for runaway (`max_velocity`, out of range) even with gravity gain 0. `tune-gravity` and `gravity-check` run without feedback. On hardware, roboloom checks `max_mA` ≤ `max_current_mA`. The leader status shows `gate`, the feedback current per joint (`mA`) and the number received under `feedback`; the trace (`<leader name>_trace.npz`) keeps it as `feedback_mA`.

The feedback current stays inside the same `max_current_mA` and EEPROM Current Limit as gravity compensation, so near the limit it is clipped. Raising the Current Limit also raises the force left on the arm if the host stops (an XC330 does not stop its current when the Bus Watchdog fires).

## Range and speed limits (limits) { #limits }

A follower's `limits` is its per-joint safety check: every joint, in order, by name. Every command of a controller passes this check. An experiment file cannot change it.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `name` | text | required | — | Joint name, in the follower's joint order |
| `min` | number | required | follower unit | Lower position bound (`min` < `max`); targets outside the range are clipped to it |
| `max` | number | required | follower unit | Upper position bound |
| `max_speed` | number | required | follower unit/s | Targets beyond it are clipped; keep it above the controller's `max_speed` ([Units](index.md#units)) |
| `max_jump` | number | required | follower unit | A command farther than this from the last target sent is rejected |

## Home pose (home) { #home }

A controller's `home:` is the saved pose that the `home` command (`infer --home`, `Session.home()`, Move home on the screen) moves to. Save poses with `roboloom capture-pose <name>`, into `poses/<follower>/<name>.yaml`.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `pose` | path | required | — | The saved pose, relative to the node file's directory (e.g. `../poses/follower/ready.yaml`) |
| `max_speed` | number | required | follower unit/s | Speed of the move; at most the controller's `max_speed` |
| `tolerance` | number | required | follower unit | How close counts as arrived |
| `timeout_s` | number | `30` | s | How long to wait for arrival |

Where it goes depends on the controller.

| Controller | Form |
| --- | --- |
| `joint` | `home: {pose, max_speed, tolerance}`; the leader moves to the matching pose too, and its current-mode groups need `homing` |
| `policy` | `home: {pose, ...}` with one follower, `{follower: {pose, ...}}` with several (followers left out stay) |
| `pose_ik` | `{follower: {pose, ...}}` |
| `parts` | Not available (nor on its inner controllers) |

## Example { #example }

```yaml
# part of a leader's node YAML
control:
- group: right_arm
  law: gravity_comp
  joints: [r_arm_sh_pitch1, r_arm_sh_roll, r_arm_sh_pitch2, r_arm_el_yaw, r_arm_wr_roll, r_arm_wr_yaw]
  gravity_model: ../calibration/gravity_right.yaml
  tuning: ../calibration/gravity_tuning_right.yaml
  max_current_mA: [150, 150, 100, 100, 60, 60]
  max_velocity: 3000
  range: ../calibration/travel_right.yaml
  homing: {kp_mA_per_count: 0.5, max_mA: 40}
- group: trigger
  law: spring
  joints: [r_arm_grip, l_arm_grip]
  rest: 2500
  goal_current_mA: 30
bus_watchdog_ms: 500
```
