# Tuning leader gravity compensation

Make the leader arm stay in place when you let go, and move only when pushed with some amount of force.
This page explains how the compensation current is determined, what `gain` and `hold_mA` mean, and how to tune each joint by hand with `roboloom tune-gravity`.

## 1. The current formula

Every control period (the leader's `poll_hz`, 120 Hz in the templates), the current for each joint is determined by the following formula.

```
sent current = clip_to_limit( ramp × ( gain × g(q) + hold − kd × velocity ) + range push-back )   [mA]
```

| Term | Meaning | Where it is set |
| --- | --- | --- |
| g(q) | Current needed to hold the joint at pose q, as predicted by the gravity model | Identified by `identify-gravity` (`calibration/gravity_<side>.yaml`) |
| gain | Multiplier applied to g(q) | `tune-gravity` (`calibration/gravity_tuning_<side>.yaml`) |
| hold | Current that pulls the joint back to where it was placed. At most ±`hold_mA` | Same as above |
| kd | Brake proportional to velocity (currently 0) | `nodes/leader_gravity.yaml` |
| ramp | Rises from 0 to 1 over the first `ramp_s` seconds after startup | Same as above |
| push-back | Applied only when outside the range of motion, proportional to the overshoot | `calibration/travel_<side>.yaml` and `barrier_mA_per_count` |
| limit | `max_current_mA`. The EEPROM Current Limit also clips to the same value on the motor side | `nodes/leader_gravity.yaml` |

Motor force (torque) is roughly proportional to current. The XC330 current unit is 1 mA.

## 2. gain: how much weight to cancel

g(q) is only a prediction. What determines the effect is the ratio "sent current ÷ actually required current"; the compensation ratio is approximately:

```
compensation ratio ≈ gain × g(q) ÷ actually required current
```

If the prediction is correct, gain 1.0 gives a 100% compensation ratio.
On our lab's unit, the holding current measured under position control came out smaller than the real value because of gear static friction. As a result, g(q) was about half of the required current.

| Example: right shoulder sh_roll, arm horizontal to the side | Value |
| --- | --- |
| g(q) | about 58 mA |
| gain 1.0 (sends 58 mA) | When released, it fell as if uncompensated |
| gain 2.0 (sends 114 mA) | Stayed (rose slightly) |
| Actually required current (estimated) | about 100 mA. About 100% at gain 1.8 |

| Compensation ratio | Joint when released |
| --- | --- |
| 0% | No compensation. Falls as if torque were off |
| around 50% | Weight is halved, but it still falls |
| about 100% | Weight disappears. Stays in place due to gear friction |
| well above 100% | Slowly rises |
| negative (wrong direction) | Falls faster |

Because of friction, there is a band in which the joint stays even if the ratio is not exactly 100%.

## 3. hold_mA: how much force it takes to start moving

It is a "hold that yields when overpowered." Think of it as friction added in software.

- The joint is pulled back to its current position by a spring (`hold_kp` mA/count, default 1.0). The pulling force does not exceed `hold_mA`.
- If you push harder than that, the hold position follows your hand. When you let go, it stops there.
- If the gravity model error is within `hold_mA`, the joint stays in any pose.
- In exchange, starting a motion takes `hold_mA` worth of extra force.
- Example: with `hold_mA: 30` and `hold_kp: 1.0`, the joint tries to return until pushed 30 counts (about 2.6°), and slides beyond that.

gain determines "how much weight to cancel"; `hold_mA` determines "how much force it takes to start moving." Tune these two separately.

## 4. Tuning by feel

| Feel | Cause | Adjustment (`tune-gravity` key) |
| --- | --- | --- |
| Slowly sinks after being placed | Insufficient compensation (error exceeds the hold) | Raise gain (`]`, +0.1) |
| Slowly rises after being placed | Overcompensation | Lower gain (`[`, −0.1) |
| Heavy or sticky when starting to move | Hold too strong | Lower `hold_mA` (`-`, −5 mA) |
| Sinks or rises depending on the pose | Per-pose prediction error | Raise `hold_mA` (`=`, +5 mA). The root fix is to re-measure under current control |

## 5. `tune-gravity` procedure

Prerequisites:
- `identify-gravity`, `measure-travel`, and `commission` are done (steps 3–6 in `.roboloom/<robot>/README.md`).
- The dataflow is stopped.

```bash
uv run roboloom tune-gravity rakuda2/experiment_gravity leader right_arm --hardware
```

1. Start it while supporting the arm. The current rises over `ramp_s` seconds. During tuning, the other group (the opposite arm) has torque off.
2. The top of the screen shows the formula, the meaning of each value, and the tuning-by-feel table. The central table shows the following values for each joint:
   - ID, gain, hold, g(q), sent current, actual current, position, velocity
   - State: `gravity` (gravity compensation only), `holding` (hold is active), `sliding` (overpowered and sliding), `free` (does nothing), `off` (gravity compensation turned off for comparison)
3. The "guide" column shows a pose in which gravity acts on the selected joint. Place the arm in that pose, let go, and watch how that joint moves.
4. Following the table in section 4, change gain and hold with the keys. Values take effect immediately.
5. Press `0` to turn off gravity compensation for that joint only, so you can compare with the uncompensated feel. Press it again to restore.
6. Move to the next joint with ↓ (or `j`). Joints with `gain 0` on which gravity has little effect (such as twist joints) are left as they are; move on to the next.
7. Save with `s` (`calibration/gravity_tuning_right.yaml`). Quit with `q`. If there are unsaved changes, a confirmation appears.
8. Tune the left arm the same way with `left_arm`.

The tuned values are used as-is by `roboloom run rakuda2/experiment_gravity --hardware`.

## 6. Safety mechanisms

- **EEPROM Current Limit:** the only protection that still works if the PC stops.
  - On the XC330, when the Bus Watchdog triggers, the current does not stop but freezes at its current value (tested on 2026-10-23).
  - Therefore, set the limit just above what is needed. Example: shoulder 150 mA, elbow 100 mA, wrist 60 mA.
  - If raising gain makes the current stick at the limit, review both `max_current_mA` and the EEPROM, and run `commission` again.
- **Runaway detection:**
  - In the following cases, torque turns off and `STOPPED` appears on the screen.
    - It moved outside the range of motion + `range_margin`.
    - A joint receiving current moved faster than `max_velocity`.
  - Support the arm, then resume with `r`.
- **Watchdog:** if control stops for `bus_watchdog_ms` (500 ms) or longer, the Watchdog triggers. This is checked when writes have paused and every 100 ms, and if it has triggered, torque is turned off. With 100 ms, occasional delays of about 130 ms triggered it.

## 7. Limits of identification and the root fix

- g(q) came out at about half its magnitude because the holding current was measured under position control.
  - With static friction, the arm can stop anywhere within the friction band.
  - Therefore, the average of two measurements, one approaching from above and one from below, does not represent gravity.
- Measuring under current control avoids this effect. Find the value at which the joint starts moving as current is gradually raised, and the value at which it starts falling as current is lowered, and take the midpoint.
- Until re-measuring, correct the magnitude with gain and absorb per-pose errors with hold.
- To check the feel numerically, use `gravity-check`. In the same pose, it releases the arm with different gain multipliers and compares how much each joint moved.

```bash
uv run roboloom gravity-check rakuda2/experiment_gravity leader right_arm --poses 1 --scales 1,0,2,-2 --hardware
```
