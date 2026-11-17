# The policy controller (policy)

| Scope | 説明 |
| --- | --- |
| `type: policy` | 全 follower を configuration 順に動かす．[Common controller keys](controllers.md#common)，[policy の実行](../../policy/index.md) |

## Loading the policy { #loading }

| Key | Type | Default | Unit | 説明 |
| --- | --- | --- | --- | --- |
| `factory` | text | `required` | — | policy を返す module:callable．Installed package，robot directory の順 |
| `kwargs` | mapping | `{}` | — | factory の引数 |

## Where it runs (backend) { #backend }

| Key | Type | Default | Unit | 説明 |
| --- | --- | --- | --- | --- |
| `backend` | text | `process` | — | process は node 内で load，server は remote inference（mock only） |
| `server` | mapping | `{}` | — | 以下の接続設定．[remote guide](../../policy/remote.md) |
| `server.address` | text | `127.0.0.1:18765` | — | server の host:port |
| `server.authkey_env` | text | `ROBOLOOM_POLICY_AUTHKEY` | — | Shared secret の環境変数名 |
| `server.timeout_s` | number | `30` | s | call の timeout |
| `server.connect_timeout_s` | number | `30` | s | 接続を待つ時間 |

## Observation and action { #observation-and-action }

| Key | Type | Default | Unit | 説明 |
| --- | --- | --- | --- | --- |
| `observe` | list[text] | `[]` | — | input/sensor source．follower state は常に含む |
| `rate_hz` | number | `required` | Hz | policy の action rate．training rate に合わせる |
| `action_horizon` | integer | `1` | actions | 各 chunk から使う action 数 |
| `max_speed` | mapping | `required` | follower unit/s | follower ごとの正の speed |
| `observation_history` | integer | `1` | frames | infer の observation[history] に N frame と直前の sent action |
| `hold` | list[text] | `[]` | — | hook の前にこれらの follower.joint target を置換．claim した hook は変更できる |
| `home` | mapping | `—` | — | Saved pose。[Home](control.md#home) |

## Inference (inference) { #inference }

| Key | Type | Default | Unit | 説明 |
| --- | --- | --- | --- | --- |
| `inference` | text | `sync` | — | sync または async（mock only）．[Guide](../../policy/async.md#asynchronous-inference) |
| `replan_at` | auto or integer | `auto` | actions | async replan の queue threshold．auto は horizon の半分，上限 horizon - 1 |

## Interpolation { #interpolation }

| Key | Type | Default | Unit | 説明 |
| --- | --- | --- | --- | --- |
| `interpolation_multiplier` | auto or integer | `auto` | — | command は rate_hz × N．整数 Hz で最も遅い follower の control_hz 以下．auto は最大の N |
| `interpolation` | text | `linear` | — | linear または pchip．[Guide](../../policy/async.md#interpolation) |

## teleop { #teleop }

| Key | Type | Default | Unit | 説明 |
| --- | --- | --- | --- | --- |
| `teleop` | list[path] | `—` | — | この file からの相対 path の joint-controller YAML．全 follower を各 1 回担当．feedback は不可．[Intervention](../../policy/intervention.md#teleop) |

## Hooks { #hooks }

| Key | Type | Default | Unit | 説明 |
| --- | --- | --- | --- | --- |
| `hooks` | list[mapping] | `[]` | — | mock only．policy controller だけ．YAML 順．[How-to](../../policy/hooks.md)，[execution](../../explanation/hooks.md) |
| `hooks[].factory` | text | `—` | — | module:callable．factory と from のいずれか 1 つ |
| `hooks[].from` | text | `—` | — | policy のみ，最大 1 回．policy が提供する writing hook に必須 |
| `hooks[].kwargs` | mapping | `{}` | — | factory 引数．from と併用不可 |
| `hooks[].writes` | list[text] | `[]` | — | 有効で重複のない follower.joint name．全 declared write を含む limit．空でなければ action.filtered を追加 |
| `hooks[].sources` | list[text] | `requirements.sources` | — | declared policy/teleop の subset．狭めることだけ可．teleop は teleop: が必要 |
| `hooks[].on_error` | text | `requirements or fail/pass` | — | fail は episode failure，hold は writable entry を held にする，pass は変更なし．writing の default は fail，observe-only は pass |
| `hooks[].budget_ms` | number | `requirements or 0.5 / rate_hz` | ms | 正の有限値．測定だけで，超過を warning/count．teleop は input period |
| `hooks[].name` | text | `Class:index` | — | 空でない log/stats 用の name |

## Load rules { #load-rules }

| Rule | 動作 |
| --- | --- |
| `options()` | policy の observation_history，hold，action_horizon が YAML より優先 |
| `--policy / --policy-kwargs` | factory/kwargs の置換は process backend のみ |
| `stale observation` | pop/step を止め follower を hold．回復後 reset と PolicyRestarted(stale_recovered) |
| `from: policy` | writing hook に slot と writes limit が必須．slot がない observe-only contribution は先頭 |
| `backend: server` | `from: policy` と空でない writes は拒否．step hook は local |
| `overlap` | 許可し，load 時に log．後の hook が優先 |
| `API` | HOOKS_API = 1．より新しい requirements は拒否 |

## Example { #example }

| Example | Link |
| --- | --- |
| Policy factory and local release gate | [Hooks](../../policy/hooks.md#configure) |
