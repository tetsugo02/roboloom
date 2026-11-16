# Asynchronous inference and interpolation

The policy node takes one action every `1/rate_hz` and interpolates in between before sending to the followers ([Rate and steps](run.md#rate-and-steps)). This page describes running inference alongside the commands, and how the interpolation works. The keys are listed in [Policy configuration](../reference/configuration/policy.md#interpolation).

## Asynchronous inference <span class="status status--mock">Mock only</span> { #asynchronous-inference }

With a slow model the followers pause at every chunk boundary while `infer` runs. `inference: async` runs `infer` on a worker thread and keeps sending the queued actions meanwhile.

```yaml
inference: async     # default sync
replan_at: auto      # start the next inference when this many actions are left
action_horizon: 16
```

- The next inference starts when `replan_at` actions are left in the queue (`auto`: half of `action_horizon`; an integer below `action_horizon` otherwise). Choose it so that the remaining actions cover the inference time: `replan_at / rate_hz` seconds.
- The new chunk replaces the queue without its first d actions, where d is the number of actions executed since the observation it was computed from. Each action keeps its place in time, as LeRobot's asynchronous rollout does. `dropped` on the controller's row shows d.
- If the queue runs out before the chunk arrives, nothing is sent and the followers hold (`late_inference`); raise `replan_at` or `action_horizon`. At the start of an episode the state is `waiting_inference` until the first chunk is there.
- Handing over to teleoperation, `stop` and a stale sensor discard the running inference's result; `policy.reset()` waits until that inference has returned, so `reset` and `infer` never overlap.
- An exception in `infer` stops the episode, as in synchronous mode ([When the policy fails during an episode](custom.md#failures)).
- The policy is taken to return a chunk that starts at the time of its observation. A policy that returns the continuation of its previous chunk on each call (a replay, for one) would lose actions when the first ones are dropped; such a policy should read `spec.inference` in `bind(spec)` and refuse `async`.
- The new chunk is not blended with the old one, and real-time chunking (RTC, which conditions a flow-matching model on the old chunk) is not implemented. A policy that returns very different consecutive chunks jumps at the switch (within `max_speed`).

## Action interpolation { #interpolation }

The policy node sends commands at `rate_hz × N` (N: `interpolation_multiplier`). It takes an action every N commands and, in between, sends the straight line from the previous action to the current one in N equal steps. The actions keep their trained spacing while the followers get fine-grained targets.

Left out (or `auto`), N is the largest that keeps `rate_hz × N` whole Hz and at most the slowest follower's `control_hz`: commands come as often as the followers take them.

| `rate_hz` | Follower `control_hz` | Computed N | Command rate |
| --- | --- | --- | --- |
| 15 | 120 (Rakuda2) | 8 | 120 Hz |
| 5 | 120 | 24 | 120 Hz |
| 7.5 | 120 | 16 | 120 Hz |
| 30 | 30 | 1 (no interpolation) | 30 Hz |

A number is used as given; `1` sends each action as is, without interpolation.

```yaml
rate_hz: 5                    # a policy trained at 5 Hz
interpolation_multiplier: 12  # cap the commands at 60 Hz (left out: 24, 120 Hz)
```

- This is the scheme of LeRobot's rollout (`interpolation_multiplier`, `lerobot.utils.action_interpolator.ActionInterpolator`) with one difference: LeRobot sends the first action as is, while roboloom interpolates from the target the follower holds to the first action.
- A follower reaches each action one action period (`1/rate_hz`, 200 ms at 5 Hz) after the action was produced.
- A given N must keep `rate_hz × N` whole Hz and at most every follower's `control_hz`; otherwise loading is refused. When no N gives whole Hz (e.g. `rate_hz: 7.33`), the computed N is 1.
- The N in use shows as `interpolation` in the policy's row on the operator screen.
- The `action` recorded in an evaluation dataset is the interpolated target actually sent to the follower.
- At a chunk boundary the interpolation also pauses while `infer` runs; the next action continues from the action reached before the pause.
- Targets are cut to `max_speed` from what each follower holds, and `FollowerSafety` checks the joint limits and the deadline, as in teleoperation.

### A smooth curve instead of the line (`interpolation: pchip`) <span class="status status--mock">Mock only</span> { #pchip }

The straight line changes its speed abruptly at every action. `interpolation: pchip` sends a monotone cubic curve (Fritsch–Carlson) through the same actions instead:

```yaml
interpolation: pchip   # default linear
```

- The targets still pass through every action at its own time, so the curve adds no lag to the line (a low-pass filter would).
- Between two consecutive actions the targets stay within their range: no overshoot, also when the policy's actions are noisy.
- The speed is continuous at the actions, as long as the action that was looked ahead to is the one executed next (see below). From the held pose the first action starts at rest. Halfway between two actions the speed can be up to 1.5 times the line's; `max_speed` still limits it.
- The curve needs the action after the one being approached, taken from the queued chunk. For the last action of a chunk (synchronous inference, or `action_horizon: 1`) there is none, and the segment ends at the line's slope. With `inference: async` the next chunk usually arrives before the queue is empty.
- The speed is not continuous in two cases. One: after a segment that had no next action to look at, when the next action reverses or differs much (a chunk boundary, `action_horizon: 1`). Two: when `inference: async` replaces the queued actions and the action that was looked ahead to changes. In both, the slope at the start of the next segment is limited again, so there is still no overshoot, but the speed jumps at that action.
- `linear` stays the default: it is LeRobot's scheme and what the checks so far were done with. Neither has been compared on hardware; replay a recorded episode ([Replaying a recording](evaluation.md#replaying-a-recording)) with each and compare the recorded `observation.state`.
