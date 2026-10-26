# Sensors

| Sensor | `type` | Output |
| --- | --- | --- |
| [RealSense](realsense.md) | `realsense_rgb` | RGB camera image |
| [DIGIT](digit.md) | `digit` | Tactile RGB image |

Supported combinations are listed in [Rakuda2](../robots/rakuda2.md). Images are handled as HWC, 3-channel RGB. A sensor's `fps` is its capture rate; an experiment's `dataset_fps` is the recording rate.
