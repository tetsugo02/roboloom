# PiPER＋Pika：設定を絞る

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> 値はこの機体で測るものです．ここの数値は例で，実機で確かめたものではありません．

- **目的**：ゆるい設定で遠隔操作できたあと，道具の寸法（`tool_offset`），作業範囲（`workspace`），関節の範囲（`limits`）を実機に合わせて書き足し，速度を上げる．
- **前提**：[初めての遠隔操作](first-teleop.md) が済んでいる．
- **結果**：手の回転が指先を中心に効き，台やもう一方の腕に向かう目標で腕が止まる．

## 1. 道具の寸法（`tool_offset`）

`tool_offset` は，フランジ（link6）から指先の中心までの位置と向きです．省略すると，フランジが道具になります．このとき手首をひねると，腕はフランジを中心に回り，指先は大きく振れます．

1. Pika Gripperを付けたまま，フランジの面から指先の中心までの距離を測ります．
2. link6のz軸はフランジの面に垂直で，外向きです．指先がその軸の上にあれば，`xyz` は `[0, 0, 距離]` です．
3. 道具の座標の向きをフランジと同じにするなら，`rpy` は `[0, 0, 0]` です．

```yaml
# nodes/left_ik.yaml（例：指先がフランジから0.17 m）
tool_offset: {xyz: [0.0, 0.0, 0.17], rpy: [0.0, 0.0, 0.0]}
```

参考：AgileXの公式の遠隔操作は，純正グリッパーに0.19 m（`gripper_xyzrpy`）を使います．Pika Gripperの値は公式にもないので測ります．

## 2. 作業範囲（`workspace`）

`workspace` は，腕の土台（base_link：土台の中心，xが前，zが上）から見た箱です（m）．目標の道具の位置が箱の外に出ると，腕は送らずに保持します（`out_of_workspace`）．

- `min` のzは台の面より少し上にします（台に当てない）．
- 両腕の間に向かうy（左の腕なら負の向き）は，もう一方の腕に届かない値にします．
- 遠隔操作で実際に使った範囲より少し広く取ります．

```yaml
# nodes/left_ik.yaml（例）
workspace: {min: [0.10, -0.15, 0.03], max: [0.55, 0.40, 0.50]}
```

## 3. 関節の範囲と速度

- `nodes/left.yaml` などの `limits` はPiPERのメーカーの範囲の内側にあるだけで，衝突を避ける範囲ではありません．台やケーブルに当たる関節は狭めます．
- 動作を確かめながら，`speed_percent`（20から），`max_speed`（腕 0.5 rad/s から），Gripperの `current_limit_A`（0.5 Aから，最大2 A）を上げます．
- 開始の姿勢を自分の作業に合わせるときは，遠隔操作で姿勢を作り，`hold` で終了してから保存します．

```bash
uv run roboloom capture-pose piper-pika left ready --force
```

## 4. 確かめる

```bash
uv run roboloom validate piper-pika   # workspace の note が消える
uv run roboloom run piper-pika
```

台に向かって手を下げ，箱の下の面で腕が止まること（`out_of_workspace`）を，ゆっくり確かめます．

## 次へ

- 記録して学習する流れは [模擬で一周する](mock.md) と同じです（構成の名前を `piper-pika` に替える）．
- 手首カメラを足すときは [Pikaの手首カメラ](../../sensors/pika-cameras.md) を参照してください．
