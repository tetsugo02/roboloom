# 方策と推論

`type: policy` のcontrollerは，学習した方策でfollowerを動かします．方策は，自分で書いたものでも，LeRobotのcheckpointでも，同じ仕組みで読み込みます．

!!! warning "確かめた範囲"
    自作の方策の経路は，Rakuda2の構成と模擬で使っています．LeRobotの方策（`roboloom.policy.lerobot`）は，模擬のPiPER＋Pikaの構成だけで確かめています．模擬で記録したdataを `lerobot-train` でCPUで短く学習したACTで，記録から推論までを通しました．実機と，十分に学習した方策では，まだ確かめていません．

## 全体の流れ { #overview }

```mermaid
flowchart LR
  obs["observation<br/>(state, images, inputs)"] --> policy["policy.infer()"]
  policy --> chunk["action chunk [H, n]"]
  chunk --> interp["interpolation<br/>rate_hz × N"]
  interp --> follower["follower<br/>(max_speed, FollowerSafety)"]
  follower --> obs
  leader["leader (teleop)"] -. intervention .-> follower
  follower --> recorder["recorder → LeRobotDataset"]
```

- 方策nodeは，followerの関節状態と `observe` に挙げた入力・sensorを観測として方策に渡します（[自作の方策](custom.md)）．
- 方策は1手 `[n]` か，まとめた行動 `[H, n]` を返します．方策nodeは `rate_hz` の周期で1手ずつ取り出し，その間を補間して，followerの制御周期に近い周期で指令を送ります（[非同期の推論と補間](async.md)）．
- 送る目標は `max_speed` で切り詰め，`FollowerSafety` が可動域と期限を検査します．遠隔操作と同じです．
- `teleop:` のある構成では，episodeの途中で人がleaderで介入し，また方策に戻せます（[teleopと介入](intervention.md)）．
- recorderは，followerに実際に送った指令を `action` に記録します（[dataの形式](../data/format.md)）．

## ページ { #pages }

| ページ | 内容 | 状態 |
| --- | --- | --- |
| [方策を動かす](run.md) | `nodes/policy.yaml`，`roboloom infer`，周期と手数，home，Pythonから，sensor選択 | <span class="status status--mock">模擬のみ</span>（sensor選択），<span class="status status--dev">開発中</span>（PiPER＋Pika） |
| [自作の方策](custom.md) | 方策の形，`bind`，観測の選択，失敗したとき，履歴と `hold`，自分のmodel | — |
| [LeRobotの方策](lerobot.md) | checkpointを読み込む，`lerobot-train` で学習する | <span class="status status--mock">模擬のみ</span> |
| [方策server](remote.md) | 方策を別のprocess・別の環境で動かす（`serve-policy`） | <span class="status status--mock">模擬のみ</span> |
| [非同期の推論と補間](async.md) | `inference: async`，行動の補間，`pchip` | <span class="status status--mock">模擬のみ</span>（非同期，`pchip`） |
| [teleopと介入](intervention.md) | `teleop:`，介入，記録のされ方 | — |
| [評価と再生](evaluation.md) | 評価の成否を残す，記録を再生する | <span class="status status--mock">模擬のみ</span>（再生） |

状態labelの意味は [状態label](../reference/status-labels.md) にあります．keyの一覧は [方策の設定](../reference/configuration/policy.md)，commandは [CLI](../reference/cli.md#infer) にあります．

## 限界 { #limitations }

- LeRobotのRTCには対応していません．非同期の推論は，行動の列を混ぜずに入れ替えます．
- ACTの時間方向の平均（`temporal_ensemble_coeff`）は，`mode: step` のときだけ働きます．
