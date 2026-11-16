# Teleoperation and interventions

With `teleop:` in the policy YAML, the leader can drive the followers: set the start pose before an episode, hand over to the policy with `start`, take over during the episode (an intervention), and hand back. The keys are listed in [Policy configuration](../reference/configuration/policy.md#teleop).

## Configuration and operations { #teleop }

```yaml
# nodes/policy_teleop.yaml (Rakuda2 option policy_teleop)
teleop: [controller.yaml]   # the controller the leader drives through (next to this file)
```

| Operation (session command) | Outside an episode | During an episode |
| --- | --- | --- |
| Teleop (`teleop`, key `t`) | Drive the followers with the leader, recording nothing | Stop the policy and hand over to the leader (an intervention) |
| Policy (`policy`, key `p`) | Not available (`start` begins with the policy) | Hand back from the leader to the policy |
| Stop teleoperating (`stop_teleop`) | End teleoperation; the followers hold | Not available (use `stop`) |
| Start (`start`) | Start the policy and the recording; after Teleop the policy takes over from there | — |

- In Python: `Session.teleop()`, `Session.policy()`, `Session.stop_teleop()` ([Session](../reference/python-api/session.md)).
- Only `type: joint` teleop controllers are supported. `pose_ik` (PiPER + Pika Sense and the like) is refused at load as not supporting takeover yet.

## Handing over { #behavior }

- **Joint by joint**: on Teleop every follower joint stops at its current target. Once the leader's joint comes within `alignment_tolerance` (of the teleop controller) of it, or crosses it, that joint follows the leader. The policy's row on the operator screen lists the joints not caught yet and their remaining difference (`pickup`).
- A gripper does not move until you squeeze the trigger to where the gripper is, so taking over never drops what it holds.
- Handing back (Policy) clears the policy's history (`policy.reset()`) and restarts the interpolation from the targets the followers hold.
- **`home` takes the leader along**: when the policy has `home:` ([home](run.md#home)), `home` moves the leader of the teleop controller to the same pose as the follower. A leader joint in a position group (`law: position`) goes to the `home` pose and is held there. Put the torso and head, which set the camera's direction, into such a group, and the camera angle stays while Teleop moves only the arms.

  ```yaml
  # control of nodes/leader.yaml (the leader used for teleop)
  - group: camera
    law: position
    joints: [torso_yaw, head_yaw, head_pitch]
  ```

  The order is `home`, then Teleop to bring the arms to the start pose when needed, then `start`.
- An ESTOP or FAULT of a follower, or a follower going silent, also ends Teleop. Pressing Teleop again takes the joints over from there.

## What is recorded { #recording }

- The recording marks the rows a person drove with `action.intervention` (1). The feature exists only in configurations with `teleop:` ([Validity flags](../data/format.md#valid)). The leader is recorded as an input too, so the dataset name differs (Rakuda2: `-eval-teleop`).
- Teleop outside an episode records nothing. The first one or two rows of an episode may still carry the person's command from just before `start` and then have `action.intervention` 1.
