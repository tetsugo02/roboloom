# One process: `InProcessSession`

`InProcessSession` reads the bus, sensors and controller on the caller's thread. For tests,
simulation and simple robots with one follower. A slow policy or sensor delays the control
period, so production collection uses `Session` (dataflow).

## From components (no YAML)

```python
from roboloom import InProcessSession, Sample
from roboloom.drivers.mock import MockBus

with InProcessSession.from_components(
    robot="my-mock",
    bus=MockBus(dimension=2),               # any object with read_positions, write_positions, enable_torque, close
    joint_names=["j1", "j2"],
    unit="count",                            # required, no default
    limits=[
        {"name": "j1", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
        {"name": "j2", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
    ],
    controller=lambda obs: [2048, 2048],     # obs["state"] and each sensor name -> next targets (or None)
    # sensors={"camera": read_fn},          # read_fn() -> Sample(value, capture_ns) or None
    # image_shapes={"camera": (480, 640, 3)}, audio_sample_rate=None,
    fps=10, control_hz=30,                   # control_hz >= fps
    output="datasets/my-mock",               # saving needs the `record` extra
    repo_id="local/my-mock",
) as session:
    session.start_episode("handover")
    session.run(3.0)                         # list of step results
    session.stop_episode()
    session.save_episode()                   # -> episode index
    session.start_episode("retry")
    session.run(1.0)
    session.discard_episode()
    session.start_inference()
    result = session.step(policy=lambda obs: obs["state"])
    session.stop_inference()
```

Other calls: `estop()`, `release()`, `close()`. Every `step()` command passes the
follower checks (deadline, dimension, finite, range, jump). The mock limits above are not
hardware values. An external bus is treated as `torque_off: falls`, `unattended: unknown`.

## From YAML

`InProcessSession.from_yaml(path, *, options=None, mock=None, sensors=None, dataset=None)`

- `path` is a file path or a robot name; `options`/`mock` as in `load_config`.
- One follower only. Refuses configurations with a motor-controlling leader (trigger
  spring, gravity compensation) and policy controllers – use `Session` for those, and for
  the real Rakuda2. Does not handle estimators. Mock configurations open the leader
  automatically.
- Extra sensors: `sensors={"camera": fn, "digit_left": fn, ...}`.
