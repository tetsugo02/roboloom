# teleopと介入

`teleop:` を書いた方策では，leaderでfollowerを動かせます．episodeの前に開始姿勢を合わせ，`start` で方策に渡し，episodeの途中で人が介入して，また方策に戻せます．keyの一覧は [方策の設定](../reference/configuration/policy.md#teleop) にあります．

## 設定と操作 { #teleop }

```yaml
# nodes/policy_teleop.yaml (Rakuda2 option policy_teleop)
teleop: [controller.yaml]   # the controller the leader drives through (next to this file)
```

| 操作画面（`t` または click） | 利用時 | `session` / `CommandInput` の command |
| --- | --- | --- |
| `TELEOP: OFF ⇄ ON` | episode の外 | `teleop` で記録せずに leader に追従する．`stop_teleop` で follower を保持する |
| `DRIVER: POLICY ⇄ LEADER` | episode 中 | `teleop` で leader に切り替え（介入），`policy` で方策へ戻す |

ボタンは現在の状態を表示します．Start（`start`）で方策の episode を始めます．teleop 中は現在の姿勢から方策が引き継ぎます．

- Pythonでは `Session.teleop()`，`Session.policy()`，`Session.stop_teleop()` を使います（[Session](../reference/python-api/session.md)）．
- 対応する teleop の controller は `type: joint` だけです．`pose_ik`（PiPER＋Pika Sense など）は，読み込み時に「介入に未対応」として断ります．

## 切り替えの動き { #behavior }

- **関節ごとにつかまえる**：leader に切り替えると，followerの関節はすべて今の目標で止まります．leaderの関節が，その関節の値に `alignment_tolerance`（teleop の controller の値）以内まで近づくか，値をまたぐと，その関節から順にleaderに追従します．操作画面の方策の行に，まだつかまえていない関節と残りの差（`pickup`）が出ます．
- gripperは，triggerをfollowerの開き具合まで握り込むまで動きません．介入した瞬間に，つかんでいる物を落とすことはありません．
- 方策へ切り替えると，方策の履歴を消し（`policy.reset()`），followerが保持している目標から補間を始め直します．
- **`home` はleaderも一緒に動かします**：方策に `home:` があると（[home](run.md#home)），`home` はfollowerと同時に，teleop の controller のleaderも同じ姿勢へ動かします．leaderの関節を位置制御（`law: position`）のgroupにしておくと，その関節は `home` の姿勢へ動いたあと，そこで固定されます．cameraの向きを決める胴体と頭をこのgroupにすれば，leader で腕だけを動かしても，cameraの角度は変わりません．

  ```yaml
  # nodes/leader.yaml（teleop で使うleader）の control
  - group: camera
    law: position
    joints: [torso_yaw, head_yaw, head_pitch]
  ```

  手順は，`home` → 必要なら teleop をオンにして腕を開始姿勢へ → `start` です．
- follower が ESTOP・FAULT になったときや信号が途絶えたときは，teleop も止まります．操作可能になってから再び leader に切り替えると，その時点から関節ごとにつかまえ直します．

## 記録のされ方 { #recording }

- 記録では，人が動かした行を `action.intervention`（1）で区別します．`teleop:` のある構成だけにある特徴量です（[有効flag](../data/format.md#valid)）．leaderも入力として記録されるので，dataset名は別になります（Rakuda2 では `-eval-teleop`）．
- episode の外の teleop は記録しません．episodeの最初の1〜2行は，`start` の直前の人の指令が残ることがあり，`action.intervention` が1になります．
