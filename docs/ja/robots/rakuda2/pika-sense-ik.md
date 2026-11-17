# Rakuda2をPika SenseとIKで動かす

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> Rakuda2 templateのoption `pika` は，模擬のdeviceだけで確かめています．腕の関節の対応表（零点のcountと向き），gripperの対応，toolのoffset，作業範囲は，どれも仮の値です．腕の逆運動学は，方向によって条件が悪くなります（[限界](#limitations)）．[実機の前に](#before-hardware) の確認を済ませるまで，実機では動かさないでください．

leaderの代わりに，腕ごとに1台のPika Senseで，逆運動学を通してRakuda2を動かします．Rakuda2やPikaに限らない2つの仕組みを，初めて使う構成です．[followerの部分](../../reference/configuration/controllers.md#parts) と，follower自身の関節の単位で扱う運動学です．

## 構成

| node | file | 内容 |
| --- | --- | --- |
| tracker `lighthouse` | `nodes/lighthouse.yaml` | libsurvive．2台のSenseを1つのnodeで扱う |
| 入力 `right_sense`，`left_sense` | `nodes/right_sense.yaml`，`nodes/left_sense.yaml` | 手の姿勢とつまみの角度（[Pika Sense](../../controllers/pose-ik.md)） |
| controller `controller` | `nodes/controller_pika.yaml` | `type: parts`．下の2つのcontrollerを持ち，17関節すべての指令を1本にまとめてfollowerへ送る |
| その内側 | `nodes/pika_right.yaml`，`nodes/pika_left.yaml` | `type: pose_ik`．`follower.right_arm` と `follower.right_gripper`（左も同じ）を動かす |
| follower `follower` | `nodes/follower.yaml` | 変更なし．`kinematics:` が腕ごとの関節の対応表を指す |

```bash
uv run roboloom run --with pika --mock
```

- 胴体と頭（部分 `body`）はどのcontrollerも動かさず，followerが保持している位置に留まります．姿勢は，胴体と一緒に回る座標系で表します．
- 対応付けは，PiPERと同じく相対です．操作者が握った時点の腕の位置から，それ以降の手の動きの分だけtoolを動かします．目標が `workspace` の外にあるか，IKが届かない間は，指令を送りません．
- followerの安全の検査，記録する `action`（17個のcount），datasetの形は，leaderでの遠隔操作と同じです．記録する入力が違うので，dataset名に `-pika` が付きます．
- IKはURDFのradで計算します．腕のcountとの換算は，IKの前後で，`calibration/follower_<side>.yaml` の対応表（関節ごとの `urdf`，`zero`，`direction`）を使って行います．rad = direction ×（count − zero）× 2π / 4096 です．
- gripperは，1関節の部分で，単位はcountです．count = `gripper_map.scale` × つまみの角度（rad）+ `gripper_map.offset` です．

## 実機の前に { #before-hardware }

1. `calibration/follower_<side>.yaml` の腕の各関節の `zero` と `direction` を実機で確かめ（`roboloom calibrate-joints`），`confirmed: true` にします．`confirmed: false` のままでは，このoptionは実機で起動しません．模擬のdeviceでは起動します．
2. Senseのつまみを閉じたときと開いたときのgripperのcountを測り，`nodes/pika_<side>.yaml` の `SET_<SIDE>_GRIPPER_CLOSED_COUNT` と `SET_<SIDE>_GRIPPER_COUNTS_PER_RAD` を埋めます．
3. この機体に合わせて `tool_offset` と `workspace` を決め，`max_speed` を低くして始めます．[Pika Sense](../../controllers/pose-ik.md) の「実機で最初にすること」に従ってください．

## 限界 { #limitations }

- **腕のIKの条件．** 同梱のURDF（`assembly_2.urdf`，CADからの書き出し）では，toolの向きを保ったままではほとんど動かせない並進の方向が，たいてい1つあります．その方向へ動かそうとすると，controllerは `unreachable` を出して保持します．これが腕の実際の形によるものか，URDFや関節の対応表の誤りによるものかは，確かめていません．向きより位置を優先して解く方法も実装していません．数値，考えられる原因，取れる手は [腕の逆運動学の条件の詳細](#ik-conditioning) にあります．
- `type: parts` の内側のcontrollerには，まだ `home` がありません．握る前に，別の方法で腕を曲げた姿勢にしてください（腕を伸ばした姿勢は特異です）．
- このoptionは `policy` と併用できません．partsのcontrollerを，方策の `teleop:` に使うこともできません．

## 腕の逆運動学の条件の詳細 { #ik-conditioning }

この節は，この問題を次に扱う人（やagent）のための記録です．内容はすべて，同梱のURDFと未確認の関節の対応表から計算したものです．実機では何も測っていません．次のcommandで再現できます．

```bash
uv run python scripts/ik_conditioning.py rakuda2
uv run python scripts/ik_conditioning.py .roboloom/piper-mock/config.yaml   # 比較用
```

**何を測ったか．** `pose_ik` は，腕の6関節で，手先の位置3つと向き3つを同時に決めます．余る自由度はありません．scriptは，関節の姿勢を3000個（URDFの零点の姿勢から±1.5 rad以内，乱数の種は1）取り，toolのJacobianの最小の特異値を求めます．関節を1 rad動かしたとき，いちばん動かしにくい方向へtoolがどれだけ動くかを表します．0に近いと，減衰最小二乗法のsolver（`roboloom.kinematics.ik.ArmModel.solve`．30回の反復，減衰0.001，1回の反復で最大0.2 rad）は許容誤差（5 mm，0.05 rad）に入れず，controllerは `unreachable` を出します．

| 最小の特異値（5% / 中央値 / 95%） | Rakuda2 右腕 | Rakuda2 左腕 | PiPER |
| --- | --- | --- | --- |
| 位置＋向き（m/rad） | 0.0004 / 0.0089 / 0.0448 | 0.0004 / 0.0100 / 0.0481 | 0.0019 / 0.0341 / 0.1230 |
| 位置だけ（m/rad） | 0.0176 / 0.0546 / 0.0857 | 0.0168 / 0.0524 / 0.0845 | 0.0568 / 0.1296 / 0.1998 |
| 向きだけ | 0.72 / 1.06 / 1.30 | 0.70 / 1.06 / 1.29 | 0.64 / 1.02 / 1.22 |
| 零点の姿勢での，最初の関節からtoolまでの距離 | 0.30 m | 0.30 m | ― |

**数値から分かること．**

- 位置だけなら，Rakuda2は中央値でPiPERの約2.4倍悪い値です．腕が短ければ，この程度の差は出ます．同じ関節の動きでも，短いてこは手先を少ししか動かせません．
- 向きも拘束すると，Rakuda2は中央値で約4倍悪く，20姿勢に1つは0.0004 m/rad未満です．この分は，腕の大きさでは説明できません．関節の並びによるものです．いちばん弱い方向は，いつもほぼ並進です（右腕の零点の姿勢では `[vx vy vz] = [-0.16, 0.30, 0.94]`）．腕はtoolを回せますが，toolを回さずにその方向へ動かすことができません．
- URDFの零点の姿勢で，右腕は完全に特異です（0.0005）．`elbow_yaw_right_dof`（motor `r_arm_sh_pitch2`）の軸と，`wrist_yaw_right_dof`（motor `r_arm_wr_roll`）の軸が平行で，どちらも基準座標系で `[0.06, 0.46, 0.89]` です．模擬のfollowerは，この姿勢（全関節2048 count）から始まります．
- **零点の姿勢で，左右の腕は鏡像になっていません．** 左腕では，同じ2つの軸が `[0.07, -0.40, 0.92]` と `[-0.28, 0.05, 0.96]` で，最小の特異値は0.011です．CADからの書き出しでは，零点の姿勢は，そのときのassemblyの姿勢で決まります．URDFの零点は，motorが2048を示す姿勢ではない可能性が高いです．対応表の「全関節 `zero: 2048`」は，関節ごとに疑う必要があります．実機で最初に確かめるのはここです．
- motorの名前とURDFの名前は，種類が食い違っています（`r_arm_sh_pitch2` ↔ `elbow_yaw_right_dof`，`r_arm_el_yaw` ↔ `elbow_pitch_right_dof`，`r_arm_wr_roll` ↔ `wrist_yaw_right_dof`，`r_arm_wr_yaw` ↔ `wrist_pitch_right_dof`）．`calibration/leader_<side>.yaml` の対応表は重力の同定のために書いたもので，`identify-gravity` は符号の組み合わせを試します．`follower_<side>.yaml` は，それを確かめずに写したものです．どちらの名前が正しいかは分かっていません．

**分かっていないこと．** URDFのlinkの長さと軸が実機と合っているか．followerの各関節の零点のcountと向き．実機でも同じ方向が弱いか．零点や向きが違えば，特異になる姿勢は変わります．ただし，6関節では姿勢を決めるのに余りがないことは変わりません．

**できること（手間の小さい順）．**

1. *実機で，codeなし*：関節の対応表を確かめます（`roboloom calibrate-joints .roboloom/rakuda2/calibration/follower_right.yaml` のあと，いくつかの姿勢を `ArmModel.fk` と比べる）．そのあとscriptを流し直します．
2. *操作で*：肘を曲げた姿勢で握り，腕を伸ばしきらないようにします．避けられるのは最悪の姿勢だけで，中央値は悪いままです．
3. *設定で*：`nodes/pika_<side>.yaml` の `ik.rotation_tolerance_rad` と `ik.damping` を大きくします．試していません．solverは向きの誤差と位置の誤差を同じ重みで扱うので，原因を直すのではなく，精度と引き換えに拒否を減らすだけです．
4. *solverで（本筋．未実装）*：向きより位置を優先します（6次元の誤差に重みを付けた減衰最小二乗法，または位置を主のtaskにして向きを零空間で合わせる方法）．あるいは向きの成分を1つ外します（5自由度のtask．tool自身の軸まわりの回転を拘束しない）．位置だけなら，条件は短い腕なりの値です．
5. *鎖で（未実装）*：胴体のyawを7つ目の関節として加えます．両腕が胴体につながっているので，2つのcontrollerが胴体を共有することになります．今の `type: parts` では，1つの関節を動かせるのは1つのcontrollerだけです．
6. *調整では変えられないもの*：腕そのものの形です．

**codeの場所．** `src/roboloom/kinematics/ik.py`（`ArmModel`，solver），`src/roboloom/kinematics/spec.py`（`KinematicSpec`：単位の対応），`src/roboloom/robots/rakuda2/follower.py`（`kinematics`），`src/roboloom/robots/rakuda2/spec.py`（`ARM_BASE`，`ARM_TIP`，`PARTS`），`src/roboloom/controllers/pose_ik.py`，`src/roboloom/robots/rakuda2/model/assembly_2.urdf`，`tests/test_rakuda_kinematics.py`，`tests/test_rakuda_pika.py`（この試験が手をx方向へ動かすのは，使っている姿勢からはz方向へ届かないためです）．

## ほかの入力とsimulator

上の部品は，使い回すためのものです．以下はどれも実装していません．

- **VRのcontroller，UMIのようなgripper．** 姿勢を出すdeviceは，`PoseInput`（`roboloom.inputs.base`．位置，quaternion，任意でつまみの角度，`tracking`，`engaged`）のsubclassにして，`roboloom.inputs.INPUTS` に登録します．`pose_ik` と `parts` はそのまま使えます．別の計算機で読むdeviceは，受け取った側の時計で時刻を付ける必要があります．
- **followerと同じ形のleader．** 関節名と単位が同じなら，`type: joint` に対応表は要りません（[Leader](../../controllers/leader.md)）．違うarmでは `joints:` を書きます．
- **別のrobot．** followerのmodelは，関節，単位，安全の性質を宣言します．腕の鎖があれば，`kinematics()` で，自分の単位からradへの対応と一緒に返します（PiPERのようにradで話すrobotは恒等です）．`PARTS` は，複数のcontrollerで分けて動かしたいfollowerだけが宣言します．`control:` の制御則（`roboloom.control`）は，Dynamixelのようなbus（count，mA，Operating Mode）を前提にしています．PiPERのように自前の位置制御を持つrobotは使いません．
- **simulator．** followerの `open_bus` は `JointBus`（`read_positions`，`write_positions`，`enable_torque`，`close`，任意で `read_state`）を返します．同じfollowerのmodelの裏に模擬のbusを置けば，controller，IK，安全の検査，記録は変わりません．実機と同じ単位（Rakuda2ならcount．同じ対応表を通す）で話せば，datasetと方策を実機と共有できます．
