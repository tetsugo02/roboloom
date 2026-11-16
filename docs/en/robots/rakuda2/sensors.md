# Rakuda2 sensors

The sensors in the Rakuda2 template and the options that enable them. Each sensor's settings are in [Sensors](../../sensors/index.md).

| Sensor | Node name | Configuration | How to enable | Status |
| --- | --- | --- | --- | --- |
| [RealSense](../../sensors/realsense.md) | `camera` | `nodes/camera.yaml` | on by default | <span class="status status--verified">Hardware-verified</span> |
| [DIGIT](../../sensors/digit.md) | `digit_left`, `digit_right` | `nodes/digit_left.yaml`, `nodes/digit_right.yaml` | option `digit` | <span class="status status--verified">Hardware-verified</span> |
| [Audio](../../sensors/audio.md) | `audio` | `nodes/audio.yaml` | choose with `--sensors` (off by default) | <span class="status status--dev">In development</span> |

- Set the serial numbers to those of your sensors. A sensor's name becomes its feature name in the dataset (`observation.images.camera` and so on).
- Each sensor needs an entry of the same name under `max_age_ms` in `nodes/recorder.yaml` ([Recorder entry](../../sensors/index.md#recorder)).

## Combinations { #combinations }

| Enabled options | Recorded sensors | Dataset name |
| --- | --- | --- |
| none | RealSense | `local/rakuda2` |
| `digit` | RealSense + left/right DIGIT | `local/rakuda2-digit` |
| `gravity`, `digit` | RealSense + left/right DIGIT | `local/rakuda2-digit` |
| `digit`, `policy` | RealSense + left/right DIGIT | `local/rakuda2-digit-eval` |

- The image features change, so `digit` on and off are separate datasets. DIGIT episodes are not appended to a RealSense-only dataset.
- Enabling `digit` does not change the policy's input. To give the DIGIT images to a policy, set `observe` in `nodes/policy.yaml` to `[camera, digit_left, digit_right]` ([Choosing observations](../../policy/custom.md#observations)).
- All options are in [Launch options and combinations](index.md#options).

## Choosing sensors { #sensor-selection }

<span class="status status--mock">Mock only</span>

The sensors to start and record (`sensors`) and the sensors the policy observes (`observe`) are chosen separately for each launch. `None` is the configuration's default, `[]` is none. The follower state is always passed.

```bash
uv run roboloom run --sensors camera,audio
uv run roboloom infer --seconds 20 --sensors camera,audio --observe camera
```

```python
with Session.launch(
    "rakuda2",
    options=["policy"],
    sensors=["camera", "audio"],
    observe=["camera"],
    policy="my_lab.policies:load",
) as session:
    session.wait_ready()
    session.record("pick", seconds=20)
```

- An empty choice is `--sensors "" --observe ""`. The launcher has separate check boxes for the sensors to start and for the policy's observations, and remembers the last choice.
- The YAML of a sensor not chosen is not read. Observing a sensor that is not started is an error.
- Sensors added by options, the left and right DIGIT included, can be chosen one by one. The choice is resolved after the options are applied.
- An optional sensor is declared in `config.yaml` as `{file: nodes/audio.yaml, default: false}`. A plain path is on by default.
- A sensor left out of `observe` is still recorded when it is started.
- When you pass a `RobotConfig`, settle the choice with `load_config(..., sensors=[...], observe=[...])`.
- The rules are in [Sensor selection](../../reference/configuration/sensors.md#sensor-selection).
