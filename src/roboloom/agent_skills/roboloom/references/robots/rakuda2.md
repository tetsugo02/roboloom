# Rakuda2 (follower) + Rakuda-mini (leader)

Hardware-verified: teleoperation with the standard and the gravity-compensated leader,
RealSense RGB and DIGIT. Units are **raw Dynamixel position counts** and **mA**; never
convert them. `roboloom init rakuda2` copies the template (the only packaged one) to
`.roboloom/rakuda2/`; package updates never overwrite it.

## Template contents (`.roboloom/rakuda2/`)

| File | Node / `type` | Notes |
| --- | --- | --- |
| `config.yaml` | – | `repo_id: local/rakuda2`, `output: datasets/rakuda2`, `dataset_fps: 15` |
| `nodes/follower.yaml` | `follower` / `rakuda2_follower` | `port`, `motor_ids`, `control_hz: 120`, `torque: true`, `record_effort: true`, `bus_watchdog_ms: null`, `registers`, `health`, `limits` |
| `nodes/leader.yaml` | `leader` / `rakuda_mini` | `poll_hz: 120`; body and arms `law: free`, triggers `law: spring` (`rest: 2500`, `goal_current_mA: 30`) |
| `nodes/leader_gravity.yaml` | `leader` / `rakuda_mini` | arms `law: gravity_comp` (reads `calibration/gravity_<side>.yaml`, `travel_<side>.yaml`, `gravity_tuning_<side>.yaml`), `bus_watchdog_ms: 500` |
| `nodes/controller.yaml` | `controller` / `joint` | joints follow the leader joints of the same name (no `joints` table), `alignment_tolerance: 300`, `max_speed: 2048`, `couplings: []`, `home` commented out |
| `nodes/camera.yaml` | `camera` / `realsense_rgb` | 640×480, `fps: 30` |
| `nodes/digit_left.yaml`, `digit_right.yaml` | `digit` | QVGA, `height: 320`, `width: 240`, `fps: 30` |
| `nodes/policy.yaml` | `policy` / `policy` | `factory: roboloom.policy:hold`, `observe: [camera]`, `rate_hz: 15`, `action_horizon: 8`, `max_speed: {follower: 1024}` |
| `nodes/policy_teleop.yaml` | `policy` / `policy_teleop` | `policy.yaml` + `teleop: [controller.yaml]` (leader before/during an episode; dataset `-eval-teleop`) |
| `nodes/recorder.yaml`, `session.yaml` | – | `max_age_ms` per recorded node; `type: terminal` |
| `calibration/leader_<side>.yaml` | – | port, joint→URDF map, `zero`, `direction`, `confirmed: false` |
| `calibration/gravity_tuning_<side>.yaml` | – | `gain`, `hold_mA` per joint (written by `tune-gravity`) |
| `*_bilateral.yaml`, `effort.yaml`, `calibration/follower_<side>.yaml` | – | paused feature; leave as is |

`SET_` placeholders: `SET_FOLLOWER_PORT`, `SET_LEADER_PORT` (node files and calibration
maps), `SET_REALSENSE_SERIAL`, `SET_DIGIT_LEFT_SERIAL`, `SET_DIGIT_RIGHT_SERIAL`. Never
fill them yourself; see "Bring-up" for where each value comes from.

## Launch options

| Option | Does | Requires / conflicts | Dataset (`repo_id`) |
| --- | --- | --- | --- |
| (none) | standard leader, `joint` controller, RealSense | – | `local/rakuda2` |
| `digit` | adds `sensors.digit_left`, `sensors.digit_right` | – | `local/rakuda2-digit` |
| `gravity` | `inputs.leader` → `nodes/leader_gravity.yaml` | – | unchanged (same features) |
| `policy` | removes leader and controller, adds `controllers.policy`; `roboloom infer` enables it | DIGIT optional, conflicts `gravity` | `local/rakuda2-eval` (`-digit-eval` with `digit`) |

`bilateral` also exists: force feedback, **not verified on hardware, paused – do not use
or set it up**. `gravity` loads only after the measurement files below exist.

## Joints, observation and action

Order (`spec.JOINTS`, motor IDs in brackets) – the same for `observation.state`,
`action`, `observation.effort` and `observation.leader`:

```text
torso_yaw[27] head_yaw[28] head_pitch[29]
r_arm_sh_pitch1[1] r_arm_sh_roll[3] r_arm_sh_pitch2[5] r_arm_el_yaw[7] r_arm_wr_roll[9] r_arm_wr_yaw[11] r_arm_grip[31]
l_arm_sh_pitch1[2] l_arm_sh_roll[4] l_arm_sh_pitch2[6] l_arm_el_yaw[8] l_arm_wr_roll[10] l_arm_wr_yaw[12] l_arm_grip[30]
```

`motor_ids` must be exactly this list in this order (startup refuses otherwise).

| Feature | Shape | Unit |
| --- | --- | --- |
| `observation.state`, `action` (names `follower.<joint>`) | 17 | counts |
| `observation.effort` (`record_effort: true`) | 17 | mA |
| `observation.leader` (leader positions; not with `policy`) | 17 | counts |
| `observation.images.camera` | 480×640×3 | RGB |
| `observation.images.digit_left`, `…digit_right` (option `digit`) | 320×240×3 | RGB |

A policy's `infer` returns counts: `[17]` or a chunk `[H, 17]`. See
[../policy.md](../policy.md) and [../recording.md](../recording.md).

## Bring-up order (the user runs every hardware step)

1. `uv run roboloom init rakuda2`; `ls /dev/serial/by-id/` for the two U2D2 ports.
2. `uv run roboloom probe <port>` per bus (read-only, bus must be free): EEPROM, non-zero
   `homing_offset` values for `registers`, and a rough `control_hz`/`poll_hz` limit. Sensor
   serials: [../sensors.md](../sensors.md). Narrow follower `limits` to the measured safe range.
3. `uv run roboloom validate` until no `SET_` remains (opens nothing).
4. `uv run roboloom commission follower`, `uv run roboloom commission leader` (writes EEPROM
   after confirmation, arms supported).
5. Set `torque: false` in `nodes/follower.yaml`; `uv run roboloom run`; check status,
   sensor rates, `start` → `stop` → `save` → `quit`.
6. Gravity leader (dataflow stopped, arms supported):
   - `uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_<side>.yaml`,
     user checks `zero`/`direction` and sets `confirmed: true`
   - `uv run roboloom measure-travel <calibration> --out .roboloom/rakuda2/calibration/travel_<side>.yaml`
   - `uv run roboloom identify-gravity <calibration> --out .roboloom/rakuda2/calibration/gravity_<side>.yaml --collect` (energizes)
   - `uv run roboloom validate --with gravity`, `uv run roboloom commission leader --with gravity`
   - `uv run roboloom tune-gravity leader right_arm --with gravity`, then `left_arm`
7. After limits, low-speed following, stop and torque-off are verified: `torque: true`,
   `uv run roboloom run --with gravity` (add `digit` for tactile), then `record`.

Details of each measurement: [../setup.md](../setup.md). Switching `gravity` on/off changes
the leader's Operating Mode; a hardware launch from a terminal shows the EEPROM diff and
writes it after confirmation.

## Mock only (not verified on hardware – say so)

- **Leader joint locking**: a `law: position` group in the active `leader*.yaml` `control`
  (every joint in exactly one group; motors must be in Operating Mode 3).
- **`couplings`** in `controller.yaml` (keys `joint`, `source`, `scale`, `reference`,
  optional `lead_ms`): adds a measured follower joint's displacement to a target.
- **`home` moves**: `home:` (`pose`, `max_speed`, `tolerance`; optional `timeout_s`) in
  `controller.yaml`, poses saved with `roboloom capture-pose <name>`; a gravity leader's arm
  groups need `homing:`. Triggered by `home`, `roboloom session home`, `Session.home()`,
  `record --home`.

## Pre-launch checks (tell the user)

- Ports are `/dev/serial/by-id/...`; IDs, models and `registers` match `probe`; FTDI
  latency timer 1 ms for 120 Hz (else lower `control_hz` and `poll_hz` together).
- Follower `limits` narrowed from the template's EEPROM bounds; `max_speed` above the
  controller's; `health.max_current_mA` reviewed.
- First run `torque: false`; it does not de-energize the leader triggers or gravity
  compensation. Support both arms at start and at `quit`.
- Align the leader to the follower until the controller is `following` (`aligning`
  refuses `start`). See [../safety.md](../safety.md).
