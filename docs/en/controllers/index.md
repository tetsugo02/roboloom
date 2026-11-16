# Controllers

The current guide describes joint-space teleoperation using the [Leader](leader.md). The controller that drives the followers with a learned policy is described in [Driving with a policy](../policy/index.md).

`inputs`, which read the operator input, `controllers`, which convert the input into commands for their followers, and `control`, which is applied to the motors, are separate settings. For the followers a controller drives and what it does when one of them stops, see "Followers and controllers" in [Configuration](../reference/configuration/index.md). For the inputs and combinations supported by each robot, see [Rakuda2](../robots/rakuda2/index.md).
