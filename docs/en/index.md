# roboloom

roboloom is a Python package that collects robot teleoperation and sensor observations and saves them to a LeRobotDataset. The current guides cover **Rakuda2, leader, RealSense RGB, and DIGIT**.

For hardware collection, `Session` launches a dora dataflow and runs the leader, follower, sensors, and recorder as separate processes. It uses Python 3.12, dora-rs / dora-rs-cli 1.0.1, and LeRobotDataset 0.6.1.

| Chapter | Contents |
| --- | --- |
| [Quick start](quick-start/installation.md) | Installation, Rakuda2 configuration, gravity compensation, teleoperation data collection |
| [Robots](robots/index.md) | Robot configurations and supported sensors and controllers |
| [Sensors](sensors/index.md) | RealSense and DIGIT configuration and image formats |
| [Controllers](controllers/index.md) | Operation with the leader, pose alignment, input deadlines |
| [Reference](reference/configuration.md) | Details of configuration, CLI, Python API, and gravity compensation |
| [Contribution](contribution.md) | Development environment, verification, docs updates that accompany feature changes |

Start with [Installation](quick-start/installation.md), then go to [Rakuda2 Quick start](quick-start/rakuda2.md). The hardware commands in the guides require the operator to check configuration values and verify behavior on each robot unit. A successful mock run or docs build does not mean the hardware has been verified.
