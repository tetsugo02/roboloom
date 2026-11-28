# Support matrix

Which controllers, sensors and policies each robot can use. What the labels mean, and the table they come from, are in [Status labels](../reference/status-labels.md). This page, the robot pages, Controllers and Sensors copy their tables from that one.

| Label | Meaning |
| --- | --- |
| <span class="status status--verified">Hardware-verified</span> | run and checked on the real robot |
| <span class="status status--mock">Mock only</span> | checked only by tests and with mock devices (`--mock`) |
| <span class="status status--dev">In development</span> | unfinished, or never run on hardware |
| <span class="status status--design">Design only</span> | not to be used as a feature |

## Robots { #robots }

| Robot | Follower `type` | Status | Page |
| --- | --- | --- | --- |
| Rakuda2 | `rakuda2_follower` | <span class="status status--verified">Hardware-verified</span> | [Rakuda2](../robots/rakuda2/index.md) |
| PiPER | `piper_follower` | <span class="status status--dev">In development</span> | [PiPER](../robots/piper/index.md) |
| Pika Gripper | `pika_gripper_follower` | <span class="status status--dev">In development</span> | [Pika](../robots/pika/index.md) |
| Your own robot | `module:Class` | <span class="status status--mock">Mock only</span> | [Adding your own robot](../tutorials/own-robot.md) |

## Controllers and inputs { #controllers }

| Robot | Leader (`joint`) | Gravity-compensated leader | Policy (`policy`) | Policy with interventions (`policy_teleop`) | Pika Sense and IK (`pose_ik`) | Force feedback (`bilateral`) |
| --- | --- | --- | --- | --- | --- | --- |
| Rakuda2 | <span class="status status--verified">Hardware-verified</span> | <span class="status status--verified">Hardware-verified</span> | <span class="status status--verified">Hardware-verified</span> | <span class="status status--verified">Hardware-verified</span> | <span class="status status--dev">In development</span> | <span class="status status--mock">Mock only</span> (paused) |
| PiPER + Pika Gripper | — | — | <span class="status status--dev">In development</span> | — (`pose_ik` cannot take interventions) | <span class="status status--dev">In development</span> | — |
| Your own robot | depends on the configuration | — | <span class="status status--mock">Mock only</span> | depends on the configuration | depends on the configuration | — |

- On Rakuda2, locking leader joints (`law: position`) and the torso-yaw compensation (`couplings`) are <span class="status status--mock">Mock only</span> ([Leader](../controllers/leader.md)).
- [Teleop outside an episode](../controllers/index.md#teleop) is available when every controller follows operator input. <span class="status status--mock">Mock only</span>
- Configuration examples per robot are in [Rakuda2 controllers](../robots/rakuda2/controllers.md) and [PiPER controllers](../robots/piper/controllers.md).

## Sensors { #sensors }

| Robot | RealSense | DIGIT | Audio | Pika wrist cameras | Web camera |
| --- | --- | --- | --- | --- | --- |
| Rakuda2 | <span class="status status--verified">Hardware-verified</span> | <span class="status status--verified">Hardware-verified</span> | <span class="status status--dev">In development</span> | — | <span class="status status--dev">In development</span> |
| PiPER + Pika Gripper | <span class="status status--dev">In development</span> | — | <span class="status status--dev">In development</span> | <span class="status status--dev">In development</span> | <span class="status status--dev">In development</span> |
| Pika Sense in the hand (no follower) | — | — | — | <span class="status status--dev">In development</span> | — |

- Audio (`mel_mono`) and the web camera (`opencv_rgb`) can be added to any robot's configuration. The web camera is in no template.
- The combinations per robot are in [Rakuda2 sensors](../robots/rakuda2/sensors.md).

## Policies { #policies }

| Robot | Your own policy | LeRobot policy | Replaying a recording | Another process (`serve-policy`) | Asynchronous inference |
| --- | --- | --- | --- | --- | --- |
| Rakuda2 | <span class="status status--verified">Hardware-verified</span> | <span class="status status--mock">Mock only</span> | <span class="status status--mock">Mock only</span> | <span class="status status--mock">Mock only</span> | <span class="status status--mock">Mock only</span> |
| PiPER + Pika Gripper | <span class="status status--dev">In development</span> | <span class="status status--dev">In development</span> | <span class="status status--dev">In development</span> | <span class="status status--dev">In development</span> | <span class="status status--dev">In development</span> |
| Your own robot | <span class="status status--mock">Mock only</span> | <span class="status status--mock">Mock only</span> | <span class="status status--mock">Mock only</span> | <span class="status status--mock">Mock only</span> | <span class="status status--mock">Mock only</span> |

- LeRobot policies have gone from recording to inference on the mock PiPER + Pika ([LeRobot policies](../policy/lerobot.md)). They have not been used on the real Rakuda2 yet.
- The policy chapter is [Policies and inference](../policy/index.md).

## Live view (Rerun) { #viewer }

| Robot | Live view (`viewer` option / `viewer:`) | Template / extra |
| --- | --- | --- |
| Rakuda2 | <span class="status status--mock">Mock only</span> | `viewer` option in template; needs `viz` |
| PiPER + Pika Gripper | <span class="status status--mock">Mock only</span> | `viewer` option in `piper-pika` template; needs `viz` |
| Your own robot | <span class="status status--mock">Mock only</span> | Set `viewer: nodes/viewer.yaml` or option `viewer`; needs `viz` |

- Keys, output targets, logged entities, and status fields are in [Viewer configuration](../reference/configuration/viewer.md); commands are in [Live view (Rerun)](../data/recording.md#live-view).
