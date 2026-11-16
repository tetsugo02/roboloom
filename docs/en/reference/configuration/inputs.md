# Inputs (inputs, trackers)

`inputs:` are the operator's devices (leader arms, hand-held devices). An input never commands a follower itself; a controller turns it into follower commands ([controllers](controllers.md)). `trackers:` are the tracking systems that measure the pose of hand-held devices.

## Keys of every input { #common }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `type` | text | required | — | The model (`rakuda_mini`, `pika_sense`) or `module:Class` |
| `poll_hz` | number | the fastest `control_hz` of the followers it drives | Hz | Rate at which the input is read ([Control rate](followers.md#control-rate)); required in a configuration without followers |

A joint input records its joint positions, in its own unit, as `observation.<input>`. A pose input records `x`, `y`, `z`, `qx`, `qy`, `qz`, `qw`, `gripper`, `tracking` and `engaged` ([Dataset features](../dataset-features.md#observation)).

## rakuda_mini { #rakuda-mini }

The Rakuda2 leader arm (Rakuda-mini). Its joint names and unit (`dynamixel_count`) are those of the Rakuda2 follower, so a `joint` controller pairs the joints of the same name. With `control` its joint groups run control laws (gravity compensation, a spring on the triggers, ...). It falls when torque goes off (`falls`) and goes limp when the session ends (`torque_off`).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `port` | text | required | — | Port of the U2D2 (`/dev/serial/by-id/...`) |
| `motor_ids` | list of integers | required | — | Motor IDs in joint order; the same fixed order as the [Rakuda2 follower](followers.md#rakuda2-follower) |
| `registers` | mapping | required | — | EEPROM values checked at startup; the same entries as the [Rakuda2 follower](followers.md#rakuda2-follower) |
| `control` | list | — | — | Control laws per joint group ([control](control.md)); without it the arm is only read |
| `bus_watchdog_ms` | integer or `null` | — | ms | The Dynamixel Bus Watchdog; required on hardware for current-mode laws |

## pika_sense <span class="status status--dev">In development</span> { #pika-sense }

A hand-held Pika Sense. Its pose comes from its Vive tracker, read by a tracking system under `trackers:`; the jaw opening and the clutch (`engaged`) come from the Sense's serial port. A `pose_ik` controller turns it into arm joints ([Pika Sense and IK](../../controllers/pose-ik.md)).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `port` | text | required | — | The Sense's serial port (`/dev/serial/by-path/...`) |
| `tracker` | `{system, serial}` | required | — | `system`: a node under `trackers:`; `serial`: the tracker's serial number (`LHR-...`) |
| `stale_ms` | number | `100` | ms | Older pose or serial values count as lost |

## Tracking systems (trackers) <span class="status status--dev">In development</span> { #trackers }

A tracking system is one node that publishes the pose of every tracked object it sees, keyed by serial number. Several inputs can share one system (one USB receiver, one calibrated world frame).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `type` | text | required | — | `libsurvive` or `module:Class` |
| `poll_hz` | number | the fastest input that reads it | Hz | Rate at which the poses are published |

### libsurvive { #libsurvive }

Lighthouse (Vive) tracking through libsurvive. Tracked objects are told apart by serial number (`LHR-...`).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `args` | list of text | `[]` | — | Extra libsurvive arguments (e.g. `[--lighthouse-gen, "2"]`) |

## Example { #example }

```yaml
# nodes/right_sense.yaml
type: pika_sense
port: SET_RIGHT_SENSE_PORT
tracker: {system: lighthouse, serial: SET_RIGHT_TRACKER_SERIAL}
stale_ms: 100
```

```yaml
# nodes/lighthouse.yaml (trackers.lighthouse of config.yaml)
type: libsurvive
args: []
```
