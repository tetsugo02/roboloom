# Project layout

## Create

```bash
uv run roboloom init rakuda2              # .roboloom/rakuda2/ and .roboloom/.gitignore
uv run roboloom init rakuda2 --root path  # another root (default .roboloom)
```

Python: `roboloom.init_project("rakuda2", root=".roboloom")`. Only `rakuda2` has a
template today. `init` refuses when the directory exists and changes nothing. It opens no
device. Other robots (PiPER, Pika) have no template: write their configuration by hand
(see [robots/piper-pika.md](robots/piper-pika.md)).

## Layout of `.roboloom/rakuda2/`

```text
.roboloom/
  .gitignore                 *.npz, logs/, datasets/, *.fifo
  logs/last_robot            launcher's last robot (not committed)
  rakuda2/
    README.md                setup steps for this robot (read it)
    config.yaml              the one configuration: roles, recorder, session, options
    nodes/                   one YAML per node, split by feature
      leader.yaml leader_gravity.yaml controller.yaml follower.yaml
      camera.yaml digit_left.yaml digit_right.yaml policy.yaml
      recorder.yaml session.yaml   (+ *_bilateral.yaml, effort.yaml: paused feature)
    calibration/             leader_<side>.yaml, gravity_<side>.yaml, travel_<side>.yaml,
                             gravity_tuning_<side>.yaml, follower_<side>.yaml
    poses/<follower>/<name>.yaml   saved home poses (roboloom capture-pose)
    my_policy.py             optional: policies found without PYTHONPATH
    logs/                    <dataset>-<time>/dora.log, *_trace.npz, last_launch.yaml
    datasets/                LeRobotDatasets (output is relative to config.yaml)
```

## Selecting a configuration

- By robot name: `rakuda2` → `.roboloom/rakuda2/config.yaml`.
- Omitted: allowed when `.roboloom/` holds exactly one robot.
- By path: any `config.yaml` path.
- The robot name is the directory name and becomes the dataset's `robot_type`.
- Paths inside the configuration (node files, `output`) are relative to `config.yaml`.

Python: `roboloom.resolve_config("rakuda2")` returns the path;
`roboloom.load_config(...)` loads and validates it (opens no device).

## `SET_` placeholders

Values that differ per physical robot are `SET_...` in the template (ports, serial
numbers, safe limits, measured offsets). `validate`, `run` and every loader refuse while
one remains in a referenced file and print where it is. Fill them from measurements, in
this order (template README): `probe` → edit node YAML → `validate` → `commission` →
`calibrate-joints` → `measure-travel` → `identify-gravity` → `tune-gravity`
(see [setup.md](setup.md)). Option-specific files are only checked when the option is on
(e.g. DIGIT serials only with `--with digit`).

With mock devices only (`--mock`, `mock=True`, `mode: mock`), `mock.yaml` next to
`config.yaml` supplies a stand-in for each `SET_...` name, so a project runs in mock
before anything was measured. Never write those stand-ins into node files, and never
put measured values into `mock.yaml`.

`.template.json` records the roboloom version and the hash of each file as `init` copied
it; `roboloom init <robot> --update` uses it to tell untouched files (replaced when the
template changed) from edited ones (kept; what they lack is listed).

## What to commit

Commit `pyproject.toml`, `uv.lock` and every YAML under `.roboloom/` (configuration,
calibration, gravity models, travel, tuning, poses). Do not commit raw measurements
(`*.npz`), `logs/`, `datasets/`, FIFOs; the generated `.gitignore` already excludes them.
