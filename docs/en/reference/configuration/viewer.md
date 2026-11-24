# Live viewer (viewer)

<span class="status status--mock">Mock only</span>

| Detail | Description |
| --- | --- |
| Scope | Optional `viewer` service node streaming live observations, actions, capture ages, and session events to Rerun ([Status labels](../status-labels.md)) |
| Usage and background | [Live view (Rerun)](../../data/recording.md#live-view), [Why the viewer is a separate node](../../explanation/viewer.md) |
| Required extra | `viz` (`lerobot[viz]==0.7.0`: `rerun-sdk`, `foxglove-sdk`; [Installation](../../get-started/installation.md)). Off when unconfigured; Rerun is not checked or imported unless enabled |

## Enabling and node file { #enabling }

| Item | Value | Notes |
| --- | --- | --- |
| Node file location | `.roboloom/<robot>/nodes/viewer.yaml` | Included in the `rakuda2` and `piper-pika` templates |
| Launch option | `options.viewer.set: {viewer: nodes/viewer.yaml}` | Included in the `rakuda2` and `piper-pika` templates; enable with `--with viewer` or `options=["viewer"]`. Has no `dataset` suffix, so `repo_id` and `output` are unchanged ([Launch options](index.md#launch-options)) |
| Top-level key | `viewer: nodes/viewer.yaml` | In `config.yaml`; enables the viewer by default. An option with `set: {viewer: null}` turns it off |
| Inheritance and mock values | `extends`, `without`, `mock.yaml` | Supported as in other node files; `SET_...` placeholders are substituted from `mock.yaml` only in `mode: mock` ([extends](index.md#extends), [placeholders](index.md#placeholders)) |
| Reserved node name | `viewer` | Cannot be used as a node name under `trackers`, `inputs`, `controllers`, `followers`, `sensors`, or `estimators` |

## Node keys { #keys }

| Key | Type | Default | Unit | Notes |
| --- | --- | --- | --- | --- |
| `rate_hz` | number | `10` | Hz | Redraw timer rate. Must be finite and positive, and either a whole number of Hz or a whole number of milliseconds per tick (e.g. `10` or `12.5` for 80 ms; [Control rate](followers.md#control-rate)) |
| `compress_images` | boolean | `true` | — | JPEG-compress RGB images before logging (`rr.Image.compress()`); `false` logs uncompressed images |
| `ip` | text or `null` | `null` | — | Host or IP address of a Rerun gRPC server (`rerun+http://<ip>:<port>/proxy`). Must be set together with `port`, or neither |
| `port` | integer (1–65535) or `null` | `null` | — | Port of the Rerun gRPC server. Must be set together with `ip`, or neither |
| `save` | path or `null` | `null` | — | Path to a `.rrd` file. Relative paths resolve from the directory of the viewer node file |
| `memory_limit` | text | `"10%"` | — | Memory budget passed via `LEROBOT_RERUN_MEMORY_LIMIT` when spawning a local Rerun window before older data is dropped |

## Output targets { #targets }

| `ip` and `port` | `save` | Behaviour | Status `target` |
| --- | --- | --- | --- |
| `null` | `null` | Spawns a local Rerun viewer window on this machine (`memory_limit` applies) | `"spawn"` |
| set | `null` | Streams over gRPC to `rerun+http://<ip>:<port>/proxy` without spawning a local window | `"<ip>:<port>"` |
| `null` | path | Writes directly to the `.rrd` file without opening a window (headless) | Resolved `save` path |
| set | path | Streams over gRPC to `<ip>:<port>` and saves to the `.rrd` file | `"<ip>:<port>"` |

## Logged entities { #entities }

| Entity path | Rerun type / timeline | Notes |
| --- | --- | --- |
| `observation.images.<sensor>` | `Image` (static) | Logged per active image sensor with `static=True` by LeRobot's helper; Rerun keeps only the newest image in the view |
| `observation.state` | `Scalars` (`roboloom` timeline) | Joined follower positions in configuration order, with history; omitted for ticks where a joined feature cannot yet be built |
| `observation.<other>` | `Scalars` (`roboloom` timeline) | Other active sources and joined vectors (e.g. `observation.leader`, `observation.effort`), with history |
| `action.<follower>` | `Scalars` (`roboloom` timeline) | Per-follower commanded positions (e.g. `action.follower`), with history. Logged only when every follower has sent a valid action of matching joint count |
| `meta/<stream>/capture_age_ms` | `Scalars` (`roboloom` timeline) | Capture age `(now - t_capture_ns) / 1e6` in ms for each stream that has sent a sample (`<source>` and `action_<follower>`), with history |
| `session/events` | `TextLog` | Session lifecycle commands (`start`, `stop`, `save`, `discard`) with optional task text |

## Status fields { #status }

| Field | Type | Values / meaning |
| --- | --- | --- |
| `state` | text | `"viewing"` while running; `"failed"` if opening the Rerun session fails (the node keeps draining events without blocking the dataflow) |
| `streams` | integer | Number of distinct input streams (`<source>` and `action_<follower>`) that have sent at least one sample |
| `drawn` | integer | Count of completed `draw` ticks |
| `errors` | integer | Count of failed `draw` or session event log calls |
| `target` | text or `null` | `"spawn"`, `"<ip>:<port>"`, or resolved `save` path |
| `error` | text | Last error message (omitted when empty). Cleared after a later successful `draw` |
