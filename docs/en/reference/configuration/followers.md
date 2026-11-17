# Followers (followers)

Keys of the node YAML under `followers:`. A follower is a device that moves on command (an arm, a gripper, ...); each needs exactly one controller ([controllers](controllers.md#followers)).

## Keys of every follower { #common }

Keys every model reads. The model fixes the joint names and the unit.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `type` | text | required | — | The model (`rakuda2_follower`, `piper_follower`, `pika_gripper_follower`) or `module:Class` |
| `control_hz` | number | required | Hz | Rate at which the node reads and writes its bus ([Control rate](#control-rate)); at least `dataset_fps` |
| `limits` | list | required | — | Per-joint range, speed and jump limits ([limits](control.md#limits)) |
| `health` | mapping | — | — | Temperature, current and other checks ([health](#health)) |
| `record_effort` | boolean | `false` | — | `true` records the effort as `observation.effort`; refused on a model that measures none |
| `torque` | boolean | `true` | — | `false` never turns torque on and records the state only (a first check on hardware) |
| `parts` | mapping | `{}` | — | Part name to a list of joints ([parts](#parts)) |
| `unattended` | text | — | — | Only when the model declares it `unknown`: the measured value (`holds` or `torque_off`) ([Behaviour without torque and when left alone](#torque-off-and-unattended)) |

### health { #health }

Every `every_ticks` periods the faults the model's driver reports are checked, so the follower latches `FAULT` before the motor's own overload shutdown.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `every_ticks` | integer | `10` | periods | Interval between checks |
| `max_temperature_c` | number | — | °C | `FAULT` above it |
| `max_current_mA` | list, one per joint | — | mA | Current limit |
| `over_current_s` | number | `1.0` | s | How long `max_current_mA` may be exceeded before `FAULT`; only with `max_current_mA` |

### parts { #parts }

Parts are groups of joints a `type: parts` controller can drive separately ([parts controller](controllers.md#parts)). The YAML's `parts: {name: [joints]}` adds to the model's own parts. A follower without parts needs nothing and is driven as a whole.

## rakuda2_follower { #rakuda2-follower }

The 17 joints of Rakuda2 on one Dynamixel bus. The unit is `dynamixel_count`, the effort `currents_mA` (mA). Its parts are `body` (torso and head), `right_arm`, `right_gripper`, `left_arm` and `left_gripper`.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `port` | text | required | — | Port of the U2D2 (`/dev/serial/by-id/...`) |
| `motor_ids` | list of integers | required | — | Motor IDs in joint order; must equal the fixed order `[27, 28, 29, 1, 3, 5, 7, 9, 11, 31, 2, 4, 6, 8, 10, 12, 30]` |
| `registers` | mapping | required | — | EEPROM values checked at startup (table below); the node does not start on a mismatch |
| `control` | list | — | — | Control laws per joint group ([control](control.md)); without it only position goals are sent |
| `bus_watchdog_ms` | integer or `null` | — | ms | The Dynamixel Bus Watchdog; required on hardware for current-mode laws |
| `kinematics` | mapping | `{}` | — | `right_arm` and `left_arm` to a joint map (output of `roboloom calibrate-joints`), for controllers that command poses (`pose_ik`) |

Each entry of `registers` is `{default: value, <joint>: value}`. `operating_mode` is required without `control`; with `control` it follows from the laws, and a contradicting value is refused.

| `registers` key | Unit | Description |
| --- | --- | --- |
| `operating_mode` | — | Operating Mode |
| `drive_mode` | — | Drive Mode |
| `homing_offset` | — | Homing Offset |
| `current_limit` | mA | Current Limit |
| `return_delay` | µs | Return Delay Time |
| `shutdown` | — | Shutdown (conditions that stop the motor) |

## piper_follower <span class="status status--dev">In development</span> { #piper-follower }

One PiPER arm (6 joints, `joint1` to `joint6`), driven by the arm's own position control (MOVE J). The unit is `rad`, the effort `efforts_Nm` (N·m). `control` is not allowed. `health` is required: the arm reports the teach button, collisions and driver faults only there. See [PiPER](../../robots/piper/index.md).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `can` | text or `{serial}` | required | — | CAN interface (e.g. `can0`), or the serial number of the USB-CAN adapter (`{serial: "0029..."}`; the current interface is looked up on open; written by `roboloom setup`) |
| `speed_percent` | integer | required | % | The firmware's joint speed scale (1 to 100) |
| `stale_ms` | number | `50` | ms | Older feedback latches `FAULT` |

## pika_gripper_follower <span class="status status--dev">In development</span> { #pika-gripper-follower }

A Pika Gripper (one joint, `gripper`), driven by the gripper's own position control. The unit is `rad`, the effort `currents_mA` (mA). `control` is not allowed. `health` is required. See [Pika](../../robots/pika/index.md).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `port` | text | required | — | Serial port (`/dev/serial/by-path/...`) |
| `current_limit_A` | number | required | A | Motor current limit sent before torque is enabled (above 0, at most 2) |
| `stale_ms` | number | `100` | ms | Older feedback latches `FAULT` |

## Behaviour without torque and when left alone { #torque-off-and-unattended }

Each follower model and each actuated input model (a leader that runs control laws) declares two safety-relevant traits. The `release` confirmation, the exit choices and the screen hints follow them.

| Trait | Value | Meaning |
| --- | --- | --- |
| `torque_off` (when torque goes off: `release`, power loss) | `falls` | Gravity pulls it down; the operator supports it |
| | `lets_go` | It stays put but lets go of what it grips (a gripper); take the object out first |
| | `stays` | Nothing moves |
| `unattended` (when roboloom stops writing to it: quit with holding, a crashed process, a lost cable) | `holds` | It keeps its last target |
| | `torque_off` | It goes limp (a bus watchdog, a driver that releases on close) |
| | `unknown` | Not established; treated like `torque_off` |

| Model | `torque_off` | `unattended` |
| --- | --- | --- |
| Rakuda2 follower | `falls` | `holds`; `torque_off` when a group runs a current-mode law (`gravity_comp`, `impedance`), which goes limp on close and on the watchdog. `current_position` and `spring` run current-based position control and keep their goal position, so they hold |
| Rakuda-mini (leader) | `falls` | `torque_off` (limp when the session ends) |
| External bus (`InProcessSession.from_components`) | `falls` | `unknown` (the worst case, since nothing is known) |
| PiPER follower <span class="status status--dev">In development</span> | `falls` | `unknown` (not checked) |
| Pika Gripper follower <span class="status status--dev">In development</span> | `lets_go` (assumed) | `unknown` (not checked) |

- "Quit with followers holding" is offered only when some follower has `unattended: holds`. The exit confirmation names the followers that do not hold and says that they go (or may go) limp. When any follower has torque, "support, release and quit" is offered even if nothing holds: a follower left enabled without commands cannot be released by roboloom after the session.
- The `release` confirmation tells you to support the `falls` devices and to take objects out of the `lets_go` devices; `stays` devices are not named. Release is confirmed for every device.
- When a follower is `RELEASED`, or latched `FAULT` or `ESTOP` and does not hold unattended, its screen row says what to do; `FAULT` and `ESTOP` stop writing to the follower (the torque stays on, so the arm does not drop). A Dynamixel bus repeats a read that failed once before it latches `FAULT` (writes are never repeated). The follower's row shows how many reads were repeated as `bus reads repeated: N`; if it keeps growing, check the cable and the USB adapter. The state of a period in which the bus could not be read keeps the time it was last read, so the recorder records rows older than `max_age_ms` as missing (`valid` 0).
- `ESTOP` holds in place and latches, whatever the traits.
- Only an `unattended` that the model declares `unknown` may be set in the follower YAML, to a measured value (`unattended: holds` or `torque_off`); `roboloom check-hold` ([CLI](../cli.md)) measures it and writes it after confirmation. A value that contradicts the model's declaration is refused when the configuration loads.

## Control rate { #control-rate }

`control_hz` in `follower.yaml` and the leader's `poll_hz` are the rates at which those nodes read and write their bus. The work of one period (reading the state, computing control laws, writing goals) must fit in the period. A higher rate makes the leader's current control and the follower's tracking finer.

A node's rate (`control_hz`, `poll_hz`, a sensor's `fps`, a policy's `rate_hz`) is a whole number of Hz, or a rate whose period is a whole number of milliseconds (30, 120, 12.5 = 80 ms). dora's timers tick nothing else, so a value such as 29.97 is refused by `validate` and at launch.

Choose the rate as follows.

1. Run `roboloom probe <port>` on each port. It shows the state read time and a rough rate limit (reading and writing take 70% of the period). `probe` never writes.
2. Set `control_hz` and `poll_hz` and check on the `run` screen. `work … ms (max …)` on the follower and leader rows is the time one period's work takes. If the maximum stays around 70% of the period or less and `tick` matches the period, the node keeps up.
3. If not, lower the rate.

A Dynamixel bus switches to Fast Sync Read (one reply packet for all motors) at startup when every motor's firmware is v45 or later. Otherwise it keeps the plain read and prints why at startup.

Measured on Rakuda2 (2026-10-27, 17 motors, 1 Mbps, FTDI latency timer 1 ms):

| Read | Time |
| --- | --- |
| State (position, velocity, current), plain Sync Read | 5.0 ms |
| State, Fast Sync Read | 4.0 ms |
| Bus Watchdog (one register), Fast Sync Read | 2.0 ms |

The wait the Dynamixel SDK does before every send (`flush`) is also skipped. It alone took about 1.9 ms of each leader period. Packets stay in order.

To save time, these reads are not done every period:

- Leader Bus Watchdog: read when goal writes have paused for half of `bus_watchdog_ms` or more, and every 100 ms. If it fired, the current-controlled joints go limp as before.
- Follower `health`: every `every_ticks` periods, one of Bus Watchdog, hardware error and temperature is read, in turn. Each value is refreshed every three times `every_ticks` periods.

The templates use 120 Hz, verified on Rakuda2 hardware (2026-10-27, 121 s):

| | Work per period (mean, max) | Period interval |
| --- | --- | --- |
| Leader (gravity compensation) | 4.3 ms, 6.8 ms | median 8.0 ms, p99.9 10.1 ms |
| Follower | 3.7 ms, 6.1 ms | 7.7 ms |

There was one stall of about 120 ms during the run. Stalls of the same size also happen at 60 Hz and are unrelated to the rate. 120 Hz assumes an FTDI latency timer of 1 ms and Fast Sync Read. If `probe` shows a lower limit, or the maximum `work` exceeds 70% of the period, lower `control_hz` and `poll_hz` (e.g. to 60).

## Example { #example }

```yaml
# nodes/follower.yaml (part; limits and health cover every joint)
type: rakuda2_follower
port: SET_FOLLOWER_PORT
motor_ids: [27, 28, 29, 1, 3, 5, 7, 9, 11, 31, 2, 4, 6, 8, 10, 12, 30]
control_hz: 120
torque: true
record_effort: true
registers:
  operating_mode: {default: 3, r_arm_grip: 5, l_arm_grip: 5}
  current_limit: {r_arm_grip: 54, l_arm_grip: 54}
health:
  every_ticks: 10
  max_temperature_c: 70
limits:
- {name: torso_yaw, min: 0, max: 4095, max_speed: 3072, max_jump: 300}
# ...
```
