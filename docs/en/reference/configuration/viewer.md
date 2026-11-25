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
| `compress_images` | boolean | `true` | — | JPEG-compress color images before logging with `rr.Image.compress()` |
| `serve` | boolean | `true` | — | With `ip: null`, start or reuse a local Rerun server with a web viewer |
| `ip` | text or `null` | `null` | — | External Rerun gRPC host or IP. Requires `port` |
| `port` | integer (1–65535) or `null` | `null` | — | gRPC port for the external or local server. A local server uses `9876` when null. With `serve: false`, setting `port` requires `ip` |
| `web_port` | integer (1–65535) | `9090` | — | HTTP port of the local server's web viewer |
| `bind` | text | `"0.0.0.0"` | — | Listen address for a new local server. The node connects to `127.0.0.1`, so the bind address must accept IPv4 loopback |
| `public_host` | text or `null` | `null` | Hostname or IP used in both parts of the shareable URL. Null uses the robot PC's hostname. The listen address comes from `bind` |
| `server_memory_limit` | text | `"25%"` | — | Live buffer budget passed to a new local server as `--server-memory-limit` |
| `open_browser` | boolean | `false` | — | Open the local server's web viewer in a browser on the robot PC |
| `save` | path or `null` | `null` | — | Path to a `.rrd` file. Relative paths resolve from the directory of the viewer node file |
| `memory_limit` | text | `"10%"` | — | Memory budget passed to `rr.spawn()` for the native viewer window |

## Output targets { #targets }

| `ip` | `serve` | `save` | Behaviour | Status `target` |
| --- | --- | --- | --- | --- |
| set | either | optional | Streams to `rerun+http://<ip>:<port>/proxy` and writes a `.rrd` if `save` is set | `"<ip>:<port>"` |
| `null` | `true` | optional | Starts or reuses a local server on `127.0.0.1:<port>` and writes a `.rrd` if `save` is set | `"127.0.0.1:<port>"` |
| `null` | `false` | path | Writes directly to the `.rrd` file (headless) | Resolved `save` path |
| `null` | `false` | `null` | Spawns a native Rerun window on the robot PC | `"spawn"` |

| Local server lifecycle | Behaviour |
| --- | --- |
| Startup | Reuses an existing listener on `127.0.0.1:<port>`. Keep `web_port` consistent with that server. For a new server, both ports must be distinct and free |
| Logs and shutdown | The detached server writes to `rerun-server.log` in the run log directory when available. It stays up after the node exits. See [Live view (Rerun)](../../data/recording.md#live-view) for the stop command |

## Logged entities { #entities }

| Entity path | Rerun type / timeline | Notes |
| --- | --- | --- |
| `observation.images.<sensor>` | `Image`, `EncodedImage`, or `DepthImage` (`roboloom` timeline) | Temporal samples per active image sensor. Each image entity gets its own spatial view |
| `observation.state` | `Scalars` (`roboloom` timeline) | Joined follower positions in configuration order, with history; omitted for ticks where a joined feature cannot yet be built |
| `observation.<other>` | `Scalars` (`roboloom` timeline) | Other active sources and joined vectors (e.g. `observation.leader`, `observation.effort`), with history |
| `action.<follower>` | `Scalars` (`roboloom` timeline) | Per-follower commanded positions (e.g. `action.follower`), with history. Logged only when every follower has sent a valid action of matching joint count |
| `meta/<stream>/capture_age_ms` | `Scalars` (`roboloom` timeline) | Capture age `(now - t_capture_ns) / 1e6` in ms for each stream that has sent a sample (`<source>` and `action_<follower>`), with history |
| `session/events` | `TextLog` (`roboloom` timeline) | Session lifecycle commands (`start`, `stop`, `save`, `discard`) with optional task text |

## Status fields { #status }

| Field | Type | Values / meaning |
| --- | --- | --- |
| `state` | text | `"viewing"` while running; `"failed"` if opening the Rerun session fails (the node keeps draining events without blocking the dataflow) |
| `streams` | integer | Number of distinct input streams (`<source>` and `action_<follower>`) that have sent at least one sample |
| `drawn` | integer | Count of completed `draw` ticks |
| `errors` | integer | Count of failed `draw` or session event log calls |
| `target` | text or `null` | Configured output target from the table above |
| `url` | text or `null` | Shareable web viewer URL with the encoded gRPC proxy address. Both use `public_host` or the robot PC's hostname. Null outside local serving or when startup fails |
| `local_url` | text or `null` | Same URL format with `localhost` in both addresses, for local use or SSH port forwarding. Available whenever `url` is available |
| `error` | text | Last startup or logging error (omitted when empty). A successful draw clears a logging error |
| `browser_error` | text | Warning when the optional browser launch fails. Omitted when empty |
