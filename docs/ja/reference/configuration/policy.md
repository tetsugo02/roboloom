# 方策のcontroller（policy）

`type: policy` のcontrollerのkeyです（templateでは `nodes/policy.yaml`）．方策を動かす手順と考え方は [方策で動かす](../../policy/index.md) の各ページにあります．

`policy` controllerは全followerを設定の順に動かします（`followers:` に全followerを並べる）．[共通のkey](controllers.md#common)（`type`，`followers`，`command_deadline_ms`，`follower_timeout_ms`）に加えて，次のkeyを読みます．

## 方策の読み込み { #loading }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `factory` | 文字列 | 必須 | — | 方策を返す `module:callable`．robotのdirectoryからも探す（[自作の方策](../../policy/custom.md)，[LeRobotの方策](../../policy/lerobot.md)） |
| `kwargs` | mapping | `{}` | — | `factory` に渡す引数（checkpointなど） |

方策が `options()` を持つと，それが返す `observation_history`，`hold`，`action_horizon` がYAMLの値より優先します．`--policy` と `--policy-kwargs` は `factory` と `kwargs` を置き換えます（`backend: server` では使えません）．

## 実行の場所（backend） { #backend }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `backend` | 文字列 | `process` | — | `process`：このnodeが方策を読み込む．`server`：方策serverにつなぐ <span class="status status--mock">模擬のみ</span> |
| `server` | mapping | `{}` | — | `backend: server` の接続先（下の表） |

`backend: server` のserverは `roboloom serve-policy --from <this file>`（または `--experiment`）で起動します．serverが `factory` と `kwargs` を読みます．使い方は [別のprocessで方策を動かす](../../policy/remote.md#running-the-policy-in-another-process) を参照してください．

| `server` のkey | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `address` | 文字列 | `127.0.0.1:18765` | — | serverの `host:port` |
| `authkey_env` | 文字列 | `ROBOLOOM_POLICY_AUTHKEY` | — | 共有の秘密を入れた環境変数の名前 |
| `timeout_s` | 数値 | `30` | s | 1回の呼び出し（`infer` など）の上限 |
| `connect_timeout_s` | 数値 | `30` | s | serverが立ち上がるのを待つ上限 |

## 観測と行動 { #observation-and-action }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `observe` | 文字列のリスト | `[]` | — | 方策に渡す入力・sensorのnode名．followerの状態は常に渡す（[観測の選び方](../../policy/custom.md#observations)） |
| `rate_hz` | 数値 | 必須 | Hz | 方策の行動の周期（学習したときの周期） |
| `action_horizon` | 整数 | `1` | 手 | 行動のchunkから使う手数．使い切ると次の推論をする |
| `max_speed` | `{follower: value}` | 必須 | followerの単位/s | 方策の目標を1周期に動かせる幅．followerごとに書く（[単位](index.md#units)） |
| `observation_history` | 整数 | `1` | frame | 2以上で，直近N frameの観測と実行した行動を `observation["history"]` で渡す |
| `hold` | 文字列のリスト | `[]` | — | 方策が動かさない `<follower>.<joint>`．保持している目標のまま（[hold](../../policy/custom.md#hold)） |
| `home` | mapping | — | — | 始める前に動く保存した姿勢（[home](control.md#home)，[使い方](../../policy/run.md#home)） |

観測した入力・sensorの最新のsampleが `recorder` の `max_age_ms.<node>` より古くなると，方策を止めます（`stale_observation`．followerは保持します）．新しくなれば `reset()` してから再開します．

## 推論の方式 { #inference }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `inference` | 文字列 | `sync` | — | `sync`：推論の間は指令しない．`async`：別のthreadで推論し，その間も残りの行動を送る <span class="status status--mock">模擬のみ</span> |
| `replan_at` | `auto` か整数 | `auto` | 手 | `async` で，残りの行動がこの数になったら次の推論を始める．`auto` は `action_horizon` の半分．`action_horizon − 1` を上限に切り詰める |

使い方は [非同期の推論](../../policy/async.md#asynchronous-inference) を参照してください．

## 補間 { #interpolation }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `interpolation_multiplier` | `auto` か整数 | `auto` | — | 指令を `rate_hz × N` で送り，行動の間をN段に分ける．`auto` は `rate_hz × N` が整数のHzで，最も遅いfollowerの `control_hz` 以下になる最大のN．1で補間しない |
| `interpolation` | 文字列 | `linear` | — | `linear`（直線）か `pchip`（行動を通る単調な3次曲線） |

整数のNを書くときは，`rate_hz × N` が整数のHzで，`control_hz` 以下でなければなりません．使い方は [補間](../../policy/async.md#interpolation) を参照してください．

## teleop { #teleop }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `teleop` | pathのリスト | — | — | leaderで動かすcontrollerのfile（このfileのdirectoryが基準）．episodeの前と途中（介入）で操作者が動かせる |

- 書けるのは `type: joint` のcontrollerだけです（`parts` と `pose_ik` は，方策から引き継げません）．`feedback` は書けません．
- `teleop` のcontrollerが，方策の全followerをちょうど1回ずつ動かすこと．
- 各関節は，leaderがその関節の保持している目標に `alignment_tolerance` 以内で近づくか通り過ぎるまで保持し，そこから追従します．
- `teleop` のcontrollerの指令は `action.intervention` が1として記録されます．

使い方は [teleopと介入](../../policy/intervention.md#teleop) を参照してください．

## 例 { #example }

```yaml
# nodes/policy.yaml
type: policy
followers: [follower]
factory: roboloom.policy:hold
kwargs: {}
observe: [camera]
rate_hz: 15
action_horizon: 8
max_speed: {follower: 1024}
command_deadline_ms: 300
```

```yaml
# nodes/policy_teleop.yaml（option policy_teleop）
extends: policy.yaml
teleop: [controller.yaml]
```
