# teleopと介入

`teleop:` を書いた方策では，leaderでfollowerを動かせます．episodeの前に開始姿勢を合わせ，`start` で方策に渡し，episodeの途中で人が介入して，また方策に戻せます．keyの一覧は [方策の設定](../reference/configuration/policy.md#teleop) にあります．

## 設定と操作 { #teleop }

```yaml
# nodes/policy_teleop.yaml（Rakuda2 のoption policy_teleop）
teleop: [controller.yaml]   # leaderで動かすときの controller（このfileの隣）
```

| 操作（session の命令） | episodeの外 | episode中 |
| --- | --- | --- |
| Teleop（`teleop`，key `t`） | 記録せずに，leaderでfollowerを動かす | 方策を止めて，leaderに切り替える（介入） |
| Policy（`policy`，key `p`） | 使えない（`start` で方策が始まる） | leaderから方策に戻す |
| Stop teleoperating（`stop_teleop`） | leaderでの操作を終え，その場で保持する | 使えない（`stop` を使う） |
| Start（`start`） | 方策と記録を始める．Teleop の後なら，そこから方策が引き継ぐ | ― |

- Pythonでは `Session.teleop()`，`Session.policy()`，`Session.stop_teleop()` を使います（[Session](../reference/python-api/session.md)）．
- 対応する teleop の controller は `type: joint` だけです．`pose_ik`（PiPER＋Pika Sense など）は，読み込み時に「介入に未対応」として断ります．

## 切り替えの動き { #behavior }

- **関節ごとにつかまえる**：Teleop を押すと，followerの関節はすべて今の目標で止まります．leaderの関節が，その関節の値に `alignment_tolerance`（teleop の controller の値）以内まで近づくか，値をまたぐと，その関節から順にleaderに追従します．操作画面の方策の行に，まだつかまえていない関節と残りの差（`pickup`）が出ます．
- gripperは，triggerをfollowerの開き具合まで握り込むまで動きません．介入した瞬間に，つかんでいる物を落とすことはありません．
- 方策に戻すとき（Policy）は，方策の履歴を消し（`policy.reset()`），followerが保持している目標から補間を始め直します．
- **`home` はleaderも一緒に動かします**：方策に `home:` があると（[home](run.md#home)），`home` はfollowerと同時に，teleop の controller のleaderも同じ姿勢へ動かします．leaderの関節を位置制御（`law: position`）のgroupにしておくと，その関節は `home` の姿勢へ動いたあと，そこで固定されます．cameraの向きを決める胴体と頭をこのgroupにすれば，Teleop で腕だけを動かしても，cameraの角度は変わりません．

  ```yaml
  # nodes/leader.yaml（teleop で使うleader）の control
  - group: camera
    law: position
    joints: [torso_yaw, head_yaw, head_pitch]
  ```

  手順は，`home` → 必要なら Teleop で腕を開始姿勢へ → `start` です．
- followerがESTOP・FAULTになったとき，信号が途絶えたときは，Teleop も止まります．もう一度 Teleop を押すと，その時点から関節ごとにつかまえ直します．

## 記録のされ方 { #recording }

- 記録では，人が動かした行を `action.intervention`（1）で区別します．`teleop:` のある構成だけにある特徴量です（[有効flag](../data/format.md#valid)）．leaderも入力として記録されるので，dataset名は別になります（Rakuda2 では `-eval-teleop`）．
- episodeの外のTeleopは記録しません．episodeの最初の1〜2行は，`start` の直前の人の指令が残ることがあり，`action.intervention` が1になります．
