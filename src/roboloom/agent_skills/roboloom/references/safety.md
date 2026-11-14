# Safety

roboloom moves real arms. These are the mechanisms and the procedure users must follow;
an agent should repeat the relevant parts whenever it prepares a hardware run.

## Follower checks (every command)

- **Soft clamp**: targets are cut to per-joint `max_speed`; clipped rows set
  `action.clamped`.
- **Hard reject → `HOLD`**: out of range, NaN, expired (`command_deadline_ms`), or a jump
  over `max_jump`. HOLD keeps sending the last target (re-targeting the measured position
  would sag under gravity).
- **Health → `FAULT`**: hardware error, temperature, sustained over-current, Bus Watchdog
  fired, stale feedback (PiPER/Pika).
- `FAULT`, `ESTOP`, `RELEASED` **latch**; nothing recovers automatically.
- Runaway detection on control laws (velocity/range) sets current 0 and torque off.
- Policies get the same checks as teleoperation.
- **The operator's process ends** (killed, crashed, its terminal or SSH session closed):
  within about a second the dataflow discards the episode in progress, the followers
  hold with torque on, and the dataflow ends. A robot never keeps following a policy
  nobody watches. Support or lower the arms before cutting their power, as after any
  quit with holding.
- **A policy raises** during an episode: the controller turns `failed`, the followers
  hold, and the episode is discarded (not saved).

## Startup checks

- Dynamixel IDs, model numbers and EEPROM (`registers`: Operating Mode, Current Limit,
  position limits, ...) are compared at startup; a mismatch refuses to start. EEPROM is
  never written while running; `roboloom commission` writes it after confirmation.
- Current-mode laws need `bus_watchdog_ms` and Current Limit ≤ `max_current_mA` on
  hardware. `impedance` needs `allow_unvalidated: true`.
- `start` requires the leader within `alignment_tolerance` of the follower (`aligning`
  state shows differences).

## Procedure for a hardware run (tell the user)

1. Template values are not safe values for their robot: narrow follower `limits` to the
   measured safe range; verify stop and torque-off on each unit.
2. First run with `torque: false` in the follower YAML to check the data path without
   moving it (the leader's trigger spring / gravity compensation is still energized).
3. Keep the arms supportable and a stop means at hand (Ctrl-G on the screen, `estop`).
4. End with `stop` → `save`/`discard` → support leader and follower → `quit`, choosing
   follower hold or supported release explicitly (Cancel is preselected).
5. A follower left holding must be supported or lowered before its power is cut.
   Followers with `unattended: unknown`/`torque_off` may go limp when roboloom stops.

## What an agent must not do

- Run device-opening commands or `Session.launch` on hardware without an explicit request.
- Raise limits, currents, `max_jump`, `max_speed`, gains or Current Limits on its own.
- Set `allow_unvalidated: true`, enable `bilateral`, or edit `registers` to silence a
  startup mismatch (use `commission` with the user present instead).
- Fill `SET_` values with guesses or mock values.
