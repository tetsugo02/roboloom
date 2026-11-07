# Troubleshooting

The CLI prints user-actionable errors as `error: <message>` without a traceback
(`RoboloomError` subclasses: `ConfigError`, `SetupError`, `HardwareError`, `SessionError`,
`roboloom.errors.Cancelled`). Fragments below are quoted from the code, so grep the
message. Errors raised inside a node (driver, recorder, missing package) reach the caller
as `SessionError` "a node failed; log <path>" or "the dataflow exited (<code>); log
<path>"; read that `dora.log` under `.roboloom/<robot>/logs/<dataset>-<time>/`.

**Never fix an error by** raising limits, currents, `max_speed`, `max_jump` or Current
Limits; setting `allow_unvalidated: true`; editing `registers` to match the motors;
guessing a `SET_` value; or deleting a dataset. See [safety.md](safety.md).

## Configuration (`load_config`, `validate`; no device opened)

| Message fragment | Cause | Fix |
| --- | --- | --- |
| `template values still to fill (see the README next to the configuration)` | A referenced file still has a `SET_...` value; each line is `<location>: SET_...` | Ask the user or name the measurement step that produces it ([project-layout.md](project-layout.md), [setup.md](setup.md)). Option files are checked only with that option on |
| `no .roboloom/<robot>/config.yaml here (create one with` | No configuration under the project root (`.roboloom/`) | Run from the project root; `roboloom init rakuda2` (only template) or write one by hand |
| `several robots under .roboloom: ...; name one` | More than one robot directory | Pass the robot name or a `config.yaml` path |
| `unknown robot 'x'; available: rakuda2` | `init` has a template only for `rakuda2` | Other robots: copy a configuration by hand ([robots/piper-pika.md](robots/piper-pika.md)) |
| `unknown options [...]; available: ...` | Option name not in `options:` | Use a listed name (`--with`, `options=[...]`) |
| `option X requires Y` / `option X cannot be used with Y` / `options X, Y cannot be used together` | `requires` / `conflicts` of the option | Enable the required one or drop one (Rakuda2: `policy` conflicts with `gravity`) |
| `options X and Y both set <role>.<node>; make one require the other or declare them as conflicts` | Two options replace the same node | Add `requires:` or `conflicts:` to one of them |
| `options.X changes the recorded features; give it` `` `dataset: <name>` `` | Your option adds/removes recorded nodes without a dataset name | Add `dataset: <short-name>` to the option |
| `unknown keys [...] (allowed: ...)`, `robots: renamed to followers`, `robot_id: ...remove robot_id` | Unknown or renamed top-level key | Rename or remove as the message says |
| `max_speed_counts_per_s was renamed` | Old controller key | `max_speed` in the follower's unit/s (policy: `{follower: ...}`) |
| `unsupported follower type 'x'; expected one of ...` (also `input`, `sensor`, `controller`) | `type:` not registered in roboloom | Use a listed type; new types are added upstream ([extending.md](extending.md)) |
| `duplicate port or sensor ID` | Two nodes name the same port/serial | Each device belongs to one node |
| `Rakuda2 motor IDs/order must match explicit canonical mapping` | `motor_ids` edited | Restore the template's list |
| `is not validated on hardware; set allow_unvalidated: true to override` | Hardware run of an unvalidated control law (`impedance`) | Do not set the flag; use a validated law |
| `needs registers.current_limit <= N mA` / `goal_current_mA ... exceeds registers.current_limit` / `current-mode law X needs bus_watchdog_ms` | Current-mode safety preconditions | Tell the user; never raise currents. Current Limit is written by `roboloom commission` with the user present |
| `no tuning file; run roboloom tune-gravity` / `not measured yet; run roboloom measure-travel` | Option `gravity` before its measurements | Do the measurement steps in order ([setup.md](setup.md)) with the user |
| `X needs real motors; ... runs in mock mode` | A setup step on a mock configuration | Setup steps are hardware only; drop `mode: mock` / `--mock` with the user present |
| `dora validate failed:` / `dora CLI unavailable; install dependencies with uv sync` | Generated dataflow invalid / `dora` not in the venv | `uv sync`; run through `uv run`; report the dora output |

## Startup on hardware (follower or leader node)

| Message fragment | Cause | Fix |
| --- | --- | --- |
| `motor configuration differs from <node> YAML:` with `model A != expected B`, `unknown model number`, `<register> X != expected Y` | EEPROM/model differs from `registers` (new or replaced motor, wrong port) | Check the port with `roboloom probe`; then `roboloom commission <node>` with the user present (it shows the plan and asks). Never edit `registers` to match |
| `software limits [a, b] outside EEPROM [lo, hi]` | Follower `limits` wider than EEPROM position limits | Narrow `limits` to the measured safe range, or commission; never widen EEPROM limits on your own |
| `operating modes differ; run` `` `roboloom commission` `` | Laws need another Operating Mode | `roboloom commission <node>` with the user present |
| `cannot open Dynamixel bus <port>`, `missing motor N`, `Dynamixel sync read failed` | Wrong port, no power, cable, or another process holds the port | Quit other runs; check power and cable; `roboloom probe` (needs the bus free) |
| `torque is on; another process may own this bus` / `torque is on; stop the dataflow first` | A setup step while a dataflow or another tool owns the bus | Quit the running dataflow first |
| `torque is on for some of these motors; support the arm, release it, then retry` | `commission` refuses torqued motors | User supports the arm and releases it |
| `PiPER on <can>: ...` / `Pika Gripper on <port>: no ... feedback` / `Pika Sense on <port>:` | CAN interface down, power, USB path | Hints in the message; creating CAN interfaces needs an administrator. In development, mock only |
| `session FIFO already exists:` | Another run of this robot, or a stale FIFO after a crash | Make sure no run is alive, then the user deletes that FIFO file |

## Session and start

| Message fragment | Cause | Fix |
| --- | --- | --- |
| `move the leader: <joint> differs by D (tolerance T)` (state `aligning`) | Leader not within `alignment_tolerance` of the follower | The user moves the leader to the follower's pose and retries. Do not widen the tolerance |
| `the follower is not at the leader:` | Follower lagging (speed/range limits) | Hold the leader still near the follower, retry |
| `not ready after 30 s:` | `wait_ready` timed out on one of the above | Same; pass a longer `timeout` only if the user is aligning |
| `controller failed:` | E.g. the policy did not load or `bind` raised | Read the error; waiting does not help |
| Controller status `stopped_by: <follower> FAULT` (or `ESTOP`); follower mode `RELEASED` | Latched FAULT/ESTOP/RELEASED; nothing recovers automatically | Read the reason in the log; user supports the arm; `quit` and relaunch after fixing the cause ([safety.md](safety.md)) |
| `release turns torque off: ...; then pass confirm=True` | `Session.release()` needs confirmation | Only after the user supports the arm |
| `no running` `` `run` `` `to send to` | `roboloom session` with no `run` alive | Start `roboloom run` first |
| `the launcher needs an interactive terminal; use run --plain` | No TTY | `roboloom run --plain` or `roboloom record` |
| `Cancelled`: `commission cancelled; nothing was written`, `stopped by the operator` | Operator declined | Nothing changed; ask the user |

## Recording, policies, extras, Python API

| Message fragment | Cause | Fix |
| --- | --- | --- |
| `existing dataset schema or FPS differs from the configuration:` (recorder log) | Features or `dataset_fps` changed against an existing `output` | New `output`, or a `dataset:` name on the option. The message also offers moving the old dataset away; that is the user's decision, so ask first. **Never delete or overwrite the dataset** |
| `No module named 'lerobot'` (recorder) / `converting needs lerobot` | `record` extra missing | `uv add 'roboloom[record]'` |
| `No module named 'pyrealsense2'` / `'digit_interface'` / `'cv2'` / `'sounddevice'` | `hardware` extra missing | `uv add 'roboloom[hardware]'` |
| `No module named 'piper_sdk'` | `piper` extra missing | `uv add 'roboloom[piper]'` |
| `pose controllers need pinocchio` | `ik` extra missing | `uv add 'roboloom[ik]'` |
| `LeRobot policies need lerobot with torch` | `policy` extra missing | `uv add 'roboloom[policy]'` (+ `lerobot[diffusion]` etc. per policy type) |
| `policy 'x': expected 'module:callable'` | Missing `:` | `my_lab.policies:load` |
| `policy 'x': No module named ...` / `has no attribute` | Module not installed nor in `.roboloom/<robot>/` | Put the file there or install the package ([policy.md](policy.md)) |
| `must return an object with reset() and infer()` | Factory returns the wrong thing | Return a `roboloom.Policy` |
| `does not fit this configuration:` | Checkpoint features vs. `observe:` | Add sources to `observe:` or map with `kwargs.rename` |
| `has no` `` `type: policy` `` `controller` | `infer` without a policy option | Declare an option named `policy` |
| `InProcessSession drives one follower` / `policy controllers run in the dora dataflow` / `a leader whose motors run control laws needs its own process` | Configuration too big for `InProcessSession` | Use `Session` ([in-process.md](in-process.md)) |
| `the installed skill differs from this roboloom's` | Skill copy outdated | `uv run roboloom skills install --force` |
| uv: Python version / `requires-python` resolution failure | Project allows Python other than 3.12 | `requires-python = ">=3.12,<3.13"` ([installation.md](installation.md)) |
