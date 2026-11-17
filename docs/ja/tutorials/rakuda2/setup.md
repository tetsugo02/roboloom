# Rakuda2：機体設定と読み取り確認

<span class="status status--verified">実機検証済み</span>

- **目的**：`.roboloom/rakuda2/` を作り，leaderとfollowerを読み取り，torqueを切ったfollowerで収集の経路を一周する．
- **前提**：[Installation](../../get-started/installation.md) が済み，Rakuda2とRakuda-mini（leader），RealSenseが接続されている．
- **所要**：1〜2時間（portと設定値の照合を含む）．
- **結果**：`validate` が通り，`run` の画面で全nodeが動き，1 episodeを保存・破棄できる．

[Installation](../../get-started/installation.md) の手順で，自分のuv projectにroboloomとrobot・実機収集用extras（`rakuda2` / `record` / `hardware` / `digit`）を追加した前提です．commandと設定fileのpathは，自分のproject rootを基準に示します．対応機器と構成は [Rakuda2](../../robots/rakuda2/index.md) を参照してください．

## 1. 機体設定と読み取り確認

```bash
uv run roboloom init rakuda2
ls /dev/serial/by-id/
```

既に `.roboloom/rakuda2/` がある場合，`init` は上書きしません．既存の機体設定を確認して使います．新しい版のtemplateに追いつかせるときは `roboloom init rakuda2 --update` を使います．projectにないfileを足し，コピーしたまま触っていないfileを置き換えます．編集したfileと測定値の入ったfileは変えず，templateだけにあるkeyとoptionを一覧にします（手で写します）．

leader / followerのU2D2 portを識別し，別のprocessが使っていない状態で読み取ります．次の `<...>` は実際のportに置き換えます．

```bash
uv run roboloom probe /dev/serial/by-id/<follower-U2D2>
uv run roboloom probe /dev/serial/by-id/<leader-U2D2>
```

| file（`.roboloom/rakuda2/` 内） | 設定・照合する内容 |
| --- | --- |
| `nodes/follower.yaml` | followerの `port`，ID・model，`registers`，実測した安全な `limits`，速度・電流・温度上限 |
| `nodes/leader.yaml`, `nodes/leader_gravity.yaml` | leaderの `port`，ID・model，`registers`，制御則 |
| `nodes/camera.yaml` | RealSenseの `serial` |
| `nodes/digit_left.yaml`, `nodes/digit_right.yaml` | 左右DIGITの `serial` |
| `calibration/leader_right.yaml`, `calibration/leader_left.yaml` | leaderの `port`，関節とURDFの対応，零点，方向 |

`config.yaml` は機体の設定で，重力補償・DIGIT・力の逆送・方策実行などの機能を起動optionとして持ちます（[設定](../../reference/configuration/index.md)）．node fileはoptionごとに `nodes/` に分かれています．

`probe` の結果から，各関節の `homing_offset` などを設定へ反映します．重力補償では動作modeとCurrent Limitを意図的に変えるので，現在のEEPROMをそのままコピーせず，後述の `commission` で設定との差を確認します．

templateの値は機体に対する安全保証ではありません．とくにfollowerの `limits.min/max` は広い初期値です．実測した安全な範囲へ狭め，停止・脱力方法も機体ごとに確かめます．通常leaderでもtriggerには通電します．

初回の経路確認では **`nodes/follower.yaml` の `torque: true` を `torque: false` に変更** します．followerのtorqueを切った状態で腕を支持してください．この設定はleader側の通電を止めません．

## 2. 通常leaderで収集経路を確認

optionを何も有効にしない構成は，通常leaderとRealSenseだけを使います．DIGITをまだ接続していなくても，option `digit` を有効にしなければ参照しません．

```bash
uv run roboloom validate
```

参照する設定に `SET_...` が残っていれば，場所が表示されます．埋めてから再検証します．実機をつなぐ前に流れを試すだけなら，`uv run roboloom validate rakuda2 --mock` と `uv run roboloom run rakuda2 --mock` が，何も埋めずに動きます．`validate` はdeviceを開かないので，実機のEEPROMや停止挙動の照合は別途必要です．

EEPROMが意図した設定と違う場合は，dataflowを止め，両腕を支えた状態で `commission` を実行します．表示された変更を確認してから承認します．EEPROMを書き込み，読み戻す操作です．

```bash
uv run roboloom commission follower
uv run roboloom commission leader
uv run roboloom run
```

`run` は端末ではまず [launcher](../../reference/cli.md) を開きます．操作 `run` を選び，optionのチェックをすべて外したまま Launch（Ctrl-S）を押します．launcherを開かずに起動するときは `uv run roboloom run --plain` を使います（行入力の画面になります）．

起動時にもID・model・EEPROMを照合し，不一致なら拒否します．画面で全nodeの状態とsensorの取得周期を確認します．leaderをfollowerの姿勢へ揃え，controllerが `following` になったら，次を順に入力します．

```text
start pipeline check
stop
save
release
quit
```

`release` の確認時はfollowerの腕を支えます．`quit` でleaderも脱力するため，leaderの腕も支えてから終了します．`quit` の確認では，保持・支持確認後の脱力・cancelから明示選択します．初期選択はcancelで，Enterだけでは終了しません．この段階ではfollowerの `torque: false` を維持し，観測・記録経路を確認します．

## 次へ

- 重力補償を使う：[Rakuda2：重力補償](gravity.md)
- すぐに収集する：[Rakuda2：teleopで収集](collect.md)
