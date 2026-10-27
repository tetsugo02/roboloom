# バイラテラル制御の設計（FACTR 2）

!!! warning "未実装の設計案"
    このページは実装の手順をまとめた設計案です．roboloomはまだ力のフィードバックを実装していません．ここにある設定キー・コマンド・ノード名は提案で，現行のroboloomでは使えません．実機での動作も確かめていません．

作成日：2026-10-27．調査対象は次のとおりです．コードは読んだだけで，実行していません．

| 対象 | 版 |
| --- | --- |
| [philiphan0109/factr2_next](https://github.com/philiphan0109/factr2_next) | `0df02c5`（2026-09-04） |
| [FACTR teleop](https://github.com/RaindragonD/factr_teleop)（初代，比較用） | `7a07ab3` |
| FACTR：Liu et al., *Force-Attending Curriculum Training for Contact-Rich Policy Learning*，RSS 2025，[arXiv:2502.17432](https://arxiv.org/abs/2502.17432) | |
| FACTR 2：Oh, Liu, Tao, Han et al., [arXiv:2606.12406](https://arxiv.org/abs/2606.12406) v2 | |

## 1．採用する方式

バイラテラル制御には，主に二つの方式があります．

| 方式 | follower | leaderへ返すもの | 必要なもの |
| --- | --- | --- | --- |
| 力逆送型（FACTR / FACTR 2） | 位置制御のまま．電流制限つき位置制御でもよい | followerが**外から受けた**関節トルクの推定値 | 外力の推定（トルクセンサー，または電流から推定） |
| 対称型（位置–位置，robopyの `bilateral_joint`） | 電流制御．両側に同じPD結合を入れる | 両者の位置差から出る結合トルク | 両腕の重力モデル，トルク定数，follower側の電流制御 |

roboloomはFACTR 2の力逆送型を採用します．理由は次のとおりです．

- followerは位置制御のまま使えます．このため，既存の `FollowerSafety`（範囲・速度・期限・変化量の検査とHOLD）がそのまま安全の仕組みとして働きます．
- 返すのは外力だけです．followerの摩擦や慣性は操作者に伝わりません．
- FACTR 2のNEXTは，トルクセンサーのない機体でもモーター電流から外力を推定します．DynamixelのRakuda2のような機体に適用できます．
- 対称型を後で加えることも妨げません（§8）．

## 2．FACTRの原理

### leaderの制御則

leaderのモーターを電流（トルク）制御で動かし，次の和を出します（論文Eq. 5）．

```text
τ = τ_feedback + τ_null + τ_grav + τ_friction + τ_limit
```

| 項 | 式（論文） | 役割 |
| --- | --- | --- |
| 力の逆送 | `τ_feedback = μ_f K_fp τ_ext − K_fd q̇`（Eq. 1） | followerの外力をleaderへ返す．`K_fp` はleaderとfollowerの最大トルクの比，`μ_f` は弱めるための係数，`K_fd` は接触時の振動を抑える減衰 |
| グリッパー | `τ_h,t = α(−k_h I_g,t) + (1−α) τ_h,t−1`，α = 0.1（Eq. 2） | followerグリッパーの電流を，指で感じる力として返す．指数移動平均をかける |
| 零空間 | `τ_null = (I − J⁺J)(−K_np (q − q_rest) − K_nd q̇)`（Eq. 3） | 冗長自由度（7軸の腕）を手先に力を出さずに休止姿勢へ寄せる |
| 重力 | RNEAで `g(q)` を計算（Eq. 4） | 腕が落ちないようにする |
| 摩擦 | 静止摩擦：低速時に符号を振動させるディザー．動摩擦：`μ_c sgn(q̇) + μ_v q̇`（付録Eq. 7–8） | 静止摩擦を切り，手で動かしやすくする |
| 可動域 | 端に近づくと反発するポテンシャル（付録Eq. 9–10） | 可動域の端で押し返す |

ハードウェア：leaderはXC330-T288-TとXM430-W210-T（約1,230ドル），followerはFranka Pandaです．制御周期は500 Hzです．Frankaが出す外力推定 `τ_ext` をそのまま使います．

論文には安定性や受動性の解析はありません．安定化の手段は，減衰 `K_fd`，弱め係数 `μ_f`，グリッパーの平滑化だけです．

### 方策の学習

外力 `τ_ext` は，ACT方策の入力に1トークンとして加えます．学習の初めは画像をぼかし，そのぼかしを徐々に弱めます（Force-Attending Curriculum）．こうして，方策が力の入力を無視しないようにします．未知物体での平均成功率は，画像のみが21.3%，画像＋力（カリキュラムなし）が61.2%，FACTRが87.5%です．

力のフィードバックありの遠隔操作は，なしに比べてタスク完了率が+64.7%，完了時間が−37.4%でした．ただし，フィードバックの有無で集めたデータから方策を学習して比べる実験はしていません．

## 3．FACTR 2とNEXTの原理

FACTR 2は，トルクセンサーのない機体にFACTRを広げます．中心はNEXT（Neural External Torque estimation）です．

```text
τ̂_ext = τ_m − τ̂_free(x_{t−H+1..t}),  x_t = [q, q̇, q_cmd − q]
```

- `τ_m` はモーター電流から求めたトルク（`K·I`）です．
- `τ̂_free` は，**接触していないとき**にモーターが出すトルクの予測です．過去H = 50ステップの関節位置，速度，追従誤差から，LSTM（2層×128）で予測します．重力・摩擦・慣性・位置制御器の応答を，まとめて学習します．
- 学習データは，接触のない自由な動作を約10分記録したものです．学習は約1分，推論は100 Hzです．
- 精度：接触時のFrankaトルクセンサーとの誤差（L1）は0.547 Nmです．外乱オブザーバーは1.471 Nmでした．
- 限界：モデルは機体ごとに学習し直す必要があります．トルクの絶対値は `K` の精度に依存します．

leaderへの返し方（Eq. 8）は `τ_feedback = K_fp τ̂_ext` です．重力・摩擦・零空間の項はFACTRのまま使います．方策の学習は，FACTRのカリキュラムからFIRSTに変わりました．FIRSTは，接触の前後を多く選ぶように学習データを再標本化します．方策の入力には，電流そのままより `τ̂_ext` のほうがよい結果でした（NIST挿入で0.567対0.431）．

## 4．factr2_nextの実装

factr2_nextはNEXTの公式実装です．Gello型のleaderでAgileX Piperを動かす遠隔操作のデモも含みます．通信はすべてROS 2の `JointState` です．

| 部分 | 内容 |
| --- | --- |
| leader | XC330-T288-T ×7，4 Mbps，電流制御（Operating Mode 0）．制御は500 Hz，follower への指令の送信は100 Hz |
| follower | Piper（CAN）．MITモード（関節PD）で，指令を受けるたびに書き込む．補間・速度制限はない |
| 外力推定 | Piperの `effort` − LSTMの予測．速度は200 Hzの差分．推定値には指数移動平均（α = 0.2）をかける |
| 接触判定 | 推定値のL1ノルムにヒステリシス（2.0で接触，1.0で非接触） |
| 返す力 | `gate · gains · τ_ext − damping · q̇` を `±max_torque` に制限 |
| gate | 接触中かつ推定値が新しい（0.2 s以内）とき1，それ以外は0．500 Hzごとに `ramp_alpha` = 0.35で追従し，急に変えない |

`factr2_feedback.py:162-176` の該当部分です．

```python
target_gate = 1.0 if self.contact and self._fresh() else 0.0
self.gate = (1.0 - self.ramp_alpha) * self.gate + self.ramp_alpha * target_gate
tau = self.gate * self.gains * self.tau_ext
tau -= self.damping * leader_joint_vel
tau = np.clip(tau, -self.max_torque, self.max_torque)
```

既定のゲインは負です（`[-0.06, -0.08, -0.08, -0.03, -0.03, -0.02]`）．推定値は「モーターが余分に出しているトルク」で，外力とは逆向きです．負のゲインは，leaderに外力と同じ向きの力を返すためと読めます（推測）．

注意すべき点：

- 配布設定では，力の逆送，重力補償，ディザーがいずれも無効です．有効なのは零空間とグリッパーのフィードバックだけです．
- READMEによると，gate・ramp・平滑化は論文の実験では使っていません．
- Piperは6軸で冗長ではありません．このため，零空間の項は固定の対角行列による弱い姿勢ばねになっています．
- follower側には指令の期限がありません．leaderが止まると，最後の目標を保持し続けます．

## 5．roboloomにすでにあるもの

| 必要なもの | roboloomの現状 |
| --- | --- |
| leaderの電流制御と制御則の合成 | `JointDevice` と制御則（`free`，`position`，`spring`，`gravity_comp`，`impedance`）．グループごとに差し替えられる |
| 重力補償 | `gravity_comp`．計測した保持電流から同定した `g(q)`（mA）を使う．トルク定数は不要 |
| 可動域 | `gravity_comp` の範囲バリア（`barrier_mA_per_count`），逸走の検査（`max_velocity`，範囲外） |
| 静止摩擦への対処 | breakaway hold（`hold_mA`）．FACTRのディザーとは逆で，「置いた所に止まる」ための項 |
| 減衰 | `kd`（mA/(count/s)） |
| followerの状態 | robotノードの `state` に `positions`，`velocities`，`currents_mA`，実際に書いた目標 `target`（= `q_cmd`）がある |
| 記録 | `record_effort: true` で `observation.effort`（電流）を記録 |
| followerの制御則 | `robot.yaml` の `control` で，follower側にも制御則を使える（電流制限つき位置制御など）．実機では未検証 |
| 安全 | `FollowerSafety`，指令の期限，Bus Watchdog の検出，estop・release・quit で leader を脱力 |

足りないもの：

1. 外力の推定（モデル残差，NEXT）．
2. followerからleaderへの戻りの経路．現在のleaderノードは `session` しか受け取りません．
3. leader側の逆送の項（gate，ramp，期限，制限）．
4. グリッパーの力の逆送．
5. 外力の記録と，推定器の学習用データの記録．

Rakuda2の腕は片側6軸＋グリッパーで冗長ではありません．このため，零空間の項は今回は扱いません．ディザーは，breakaway holdと目的が逆なので，必要になったときに別の制御則として検討します．

## 6．設計

### 単位と符号

roboloomは関節の値をモーターの生の単位（count，mA）で扱います．重力モデルもmAで同定し，トルク定数を推定に含めます．逆送もこの方針に合わせます．

- 推定器は，follower関節ごとに `residual` を出します．単位はfollowerの電流の単位（DynamixelならmA）です．
- 定義は `residual = 実測の電流 − 自由運動での予測電流` です．モーターが外力に逆らって余分に出している分です．
- 外力は `−residual` の向きにかかります．
- leaderへの電流は次の式で求めます．`sign` はcontrollerの `joints` 対応にある符号です．

```text
i_feedback[leader j] = − k_j · sign_j · residual[follower j]
```

- `k_j`（leaderのmA / followerのmA）の目安は，FACTRの `K_fp` と同じく，leaderとfollowerの最大トルクの比に弱め係数をかけたものです．Rakuda2では，XC330とXM430/XM540のトルク定数の比が入ります．
- `torque_constant_Nm_per_A` を関節ごとに設定した機体では，N·mでも表示します．Frankaのように外力をN·mで出す機体では，推定器の単位を `Nm` と宣言し，`k_j` の単位をmA/Nmにします．
- 符号は，1関節ずつ実機で確かめます（§7 段階5）．

### dataflow

```text
leader ──sample──► controller ──command──► robot ──state──► estimator
  ▲                    │  ▲                                  │
  └──── feedback ──────┘  └────────────── estimate ──────────┘
```

| ノード | 追加する入出力 | 役割 |
| --- | --- | --- |
| estimator（新しい役割 `estimators`） | 入力 `<robot>/state`（最新1件），出力 `estimate`，`status` | followerの状態から `residual` と接触の判定を出す．重い推論で robot ノードの周期を乱さないよう，別プロセスにする |
| controller | 入力 `<estimator>/estimate`（最新1件），出力 `feedback` | follower関節の残差を `joints` の対応でleader関節へ写し，`gain` をかけ，期限をつけて送る．followerが `ACTIVE` でない，または整列前（`following` 以外）のときは0を送る |
| leader | 入力 `<controller>/feedback`（最新1件） | 制御則に逆送の項を足す．期限・gate・ramp・制限はleader側で毎周期かける |

- 関節の対応と符号は，controllerの `joints` だけに書きます．逆送用に別の対応表を作りません．
- 逆送の指令は，robotへの指令と同じく，絶対時刻の期限を持ちます（`make_command` と同じ形）．
- 経路は循環します（leader → controller → robot → estimator → controller → leader）．dora-rsのdataflowで循環する辺が使えるかは，段階1で模擬で確かめます．

### 実験の書き方

利用者は辺を書きません．今のroboloomと同じく，実験YAMLにはノードを役割ごとに並べるだけです．`runtime/flow.py` が，各ノードの参照から辺を導きます．

```yaml
# experiment_bilateral.yaml
inputs:
  leader: nodes/leader_bilateral.yaml        # type: rakuda_mini
controllers:
  controller: nodes/controller_bilateral.yaml
robots:
  robot: nodes/robot.yaml                     # type: rakuda2_follower
estimators:
  effort: nodes/effort.yaml                   # robot: robot
```

組み合わせは参照だけで決まります．

| 参照 | 書く場所 | 導かれる辺 |
| --- | --- | --- |
| `input: leader`，`robot: robot` | controller | `leader/sample` → controller，controller `command` → robot（今と同じ） |
| `robot: robot` | estimator | `robot/state` → estimator |
| `feedback.estimator: effort` | controller | `effort/estimate` → controller，controller `feedback` → `leader`（controllerの `input`） |

この規則は1組ごとに閉じています．双腕を別々のrobotとして扱う場合や，別の機体の組を同じ実験に置く場合も，組の数だけノードを並べれば辺が決まります（現在の「1実験にrobotは1台」の制限は別の課題です）．例えば，別のfollowerと別のleaderの組は次のように書けます．機体名は例で，今のroboloomにはありません．

```yaml
inputs:
  leader: nodes/leader.yaml                   # type: gello_dynamixel（例）
controllers:
  controller: nodes/controller.yaml           # type: joint, feedback.estimator: effort
robots:
  robot: nodes/robot.yaml                     # type: piper_follower（例）
estimators:
  effort: nodes/effort.yaml                   # type: next, robot: robot
```

### 機器が申告する能力

設定を読む時点で，組み合わせが成り立つかを確かめます．機体の種類で分岐せず，各クラスが申告する値で判断します．

| 申告する側 | 値 | 確かめること |
| --- | --- | --- |
| follower（`Robot`） | `effort_signal`：`state` が持つ力の量（`currents_mA`，`torques_Nm`，`external_torques_Nm` のどれか）と単位 | 推定器の入力と合うか．`sensor` は `external_torques_Nm` を出す機体だけに使える |
| leader（`JointInput`） | 逆送を受けられる関節（電流制御の制御則に `feedback` を書いたグループ）と，その単位（`mA`，`Nm`） | `feedback.gain` に書いた関節がすべて受けられるか |
| controller | `feedback.gain` の単位（leaderの単位 / followerの単位） | 単位が両側の申告と一致するか．逆送する関節が `joints` で1対1に対応するか |
| estimator | `robot`，`joint_names`，`unit`，必要な `state` の項目 | 参照するrobotが存在し，項目を出すか |

逆送の項は，`gravity_comp` だけでなく，電流制御のすべての制御則（`CurrentLaw` の派生）に共通の部品として入れます．別のleaderが別の制御則を使っても，同じ設定で逆送を受けられます．

### メッセージ

機器の違いを黙って取り違えないよう，メッセージに関節名と単位を入れます．

| kind | payload |
| --- | --- |
| `effort_estimate` | `joints`（follower），`residual`，`unit`，`contact`，`valid`，`robot_t_ns`（元の状態の時刻） |
| `feedback` | `joints`（leader），`effort`，`unit`，`deadline_ns`，`gate`（controller側の開閉の希望） |

leaderは，自分の関節名と単位に合わないメッセージを捨て，statusに理由を出します．

### 設定の案

`nodes/controller_bilateral.yaml`（既存の `joints` などに足す）：

```yaml
feedback:
  estimator: effort               # experiment.yaml の estimators の名前
  deadline_ms: 100
  unit: mA/mA                     # leaderの単位 / followerの単位
  gain:                           # 書いた関節だけ逆送する（followerの関節名）
    r_arm_sh_pitch1: 0.1
    r_arm_el_yaw: 0.1
```

`nodes/leader_bilateral.yaml` の腕のグループ：

```yaml
- group: right_arm
  law: gravity_comp               # 電流制御の制御則ならどれでもよい
  # ... 既存の gravity_model, tuning, range など
  feedback:
    max_mA: 40                    # 逆送分だけの上限．合計は従来どおり max_current_mA で制限
    ramp_s: 0.3                   # gateの開閉にかける時間
    contact_on: 30                # |residual| のL1ノルム．ヒステリシス
    contact_off: 15
    kd: 0.0                       # 接触中の追加の減衰
```

`nodes/effort.yaml`：

```yaml
type: model_residual              # none | sensor | model_residual | next
robot: robot
joints: [r_arm_sh_pitch1, r_arm_sh_roll, r_arm_sh_pitch2, r_arm_el_yaw, r_arm_wr_roll, r_arm_wr_yaw]
model: ../calibration/effort_gravity_right.yaml
smoothing_alpha: 0.2
```

### 推定器の契約

推定器は，robot・input・sensorと同じく，`type` からクラスを選ぶ登録表 `ESTIMATORS`（`roboloom/estimators/`）に置きます．機体に依存しない推定器は `roboloom/estimators/` に，特定の機体だけのものは `roboloom/robots/<model>/` に実装し，同じ登録表へ登録します．

```python
class EffortEstimator(Protocol):
    robot: str                        # 参照するrobotノード
    joint_names: tuple[str, ...]      # follower関節
    unit: str                         # "mA" や "Nm"
    needs: tuple[str, ...]            # 使う state の項目，例 ("positions", "velocities", "currents_mA", "target")
    def reset(self) -> None: ...
    def update(self, state: dict, t_ns: int) -> Estimate: ...   # robot_state の payload

@dataclass
class Estimate:
    residual: list[float]             # 実測 − 自由運動の予測
    contact: bool
    valid: bool                       # 履歴が足りない，状態が古い，などで False
```

| `type` | 中身 | 用途 |
| --- | --- | --- |
| `none` | 常に `valid=False` | 経路の試験，逆送なし |
| `sensor` | 機体が出す外力推定をそのまま使う（Franka の `tau_ext` など） | トルクセンサーのある機体 |
| `model_residual` | `currents_mA − g_f(q)`．`g_f` は既存の回帰の重力モデルをfollowerで同定したもの | 最初の基準．学習なしで動く．摩擦と慣性は残差に残る |
| `next` | `currents_mA − LSTM(q, q̇, target − q)` | FACTR 2と同じ方法 |

機体の固有の部分は推定器の実装と設定に閉じ込めます．controllerとleaderは，`Estimate` だけを見ます．

### モデルの保存先

計測した値と学習した重みは，機体（1台ごと）の設定と一緒に `.roboloom/<機体>/`（`roboloom init <機体>` が作るディレクトリ）に置きます．パッケージには入れません．今の重力モデルと同じく，YAMLはGitで管理し，大きな生データと重みは除外します．

| 場所 | 中身 | Git |
| --- | --- | --- |
| `calibration/effort_gravity_<side>.yaml` | `model_residual` 用のfollowerの重力モデル（既存の回帰の形式） | 管理する |
| `models/<推定器名>/<run_id>/model.yaml` | NEXTのmanifest（下表） | 管理する |
| `models/<推定器名>/<run_id>/weights.safetensors` | 学習した重み | 除外（`*.safetensors`） |
| `logs/<run>/robot_trace.npz` | 学習用の自由運動のデータ（段階2のトレース） | 除外（既存の `*.npz`，`logs/`） |

- `run_id` は学習した日時です（例 `20261101-153000`）．ノードYAMLは版を明示して指定します．「最新」を自動で選びません．どのモデルで動いたかを再現できるようにするためです．
- 重みはsafetensorsで保存します．pickleを使わないので，読み込みでコードが実行されません．`torch` は optional extra（`next`）にします．
- データセットには，記録に使った推定器の `type` と `run_id` を残します．

manifest（`model.yaml`）に書く内容：

| 項目 | 例 |
| --- | --- |
| 形式 | `format: 1`，`type: next` |
| 機体 | robotの `type`，ノード名，`port`（by-id，個体の識別），関節名，モーターID |
| 入力 | 特徴量と順序（`positions`，`velocities`，`target - positions`），単位，**`rate_hz`**，履歴の長さ，正規化の平均と分散 |
| モデル | 構造（LSTM 2×128 など），学習の設定 |
| データ | 使った `logs/` のパスと各ファイルのsha256 |
| 評価 | 検証データでの誤差，既知の重りでの確認結果 |
| 由来 | 重みのsha256，作成日時，roboloomのcommit |

読み込み時に次を確かめ，合わなければ起動を拒否します．

- robotの `type`，関節名，モーターIDが一致すること．
- `rate_hz` がrobotの `control_hz` と一致すること．NEXTの履歴の長さは周期で決まるので，周期を変えたら学習し直します．
- 重みのsha256が一致すること．
- `port` が同じ個体であること．別の個体に使うときは，明示的に許可する設定を要求します．

`roboloom init` のテンプレートには，`models/` の説明と `.gitignore` の `*.safetensors` を加えます．

### 安全

- 逆送は既定で無効です．`feedback.gain` に書いた関節だけ有効になります．
- 期限切れ，`valid=False`，followerの `HOLD`・`FAULT`・`ESTOP`，controllerの整列前では，gateを0へ `ramp_s` で閉じます．急に0にしません．
- `estop`・`release`・`quit` では，今までどおりleaderを脱力します．
- 逆送の電流は，まず `feedback.max_mA` で制限します．その後，重力・hold・バリアと足した合計を，従来の `max_current_mA` で制限します．
- EEPROMのCurrent Limitは，ホストが止まったときに残る唯一の上限です．XC330では，Bus Watchdogが発火しても電流は止まりません．逆送の分だけCurrent Limitを上げるときは，その値を `commission` で書き，危険を理解した上で行います．
- 既存の逸走の検査（`max_velocity`，範囲外）は，逆送中も働きます．
- follower側は今までどおり `FollowerSafety` が守ります．follower を電流制限つき位置制御（Operating Mode 5）にすると，接触時の力も上限で抑えられます．

## 7．実装の手順

各段階でコミットし，模擬の試験を通してから実機に移ります．実機での確認は利用者が行います．

| 段階 | 内容 | 完了の条件 |
| --- | --- | --- |
| 1．経路 | `estimators` の役割，登録表 `ESTIMATORS`，`none` 推定器を加える．各クラスの能力の申告と，設定読み込み時の照合を入れる．`flow.py` で参照から辺を導き，controller の `feedback` 出力と leader の `feedback` 入力を作る．逆送の値は常に0 | 模擬dataflowで，循環する辺，feedbackの期限，最新1件の受け渡し，単位や関節が合わない設定の拒否を試験で確かめる．既存の試験が通る |
| 2．followerの記録 | robotノードに毎周期のトレース（`positions`，`velocities`，`currents_mA`，`target`，`mode`）を加える．leaderの `leader_trace.npz` と同じ形にする．推定器の出力を `observation.effort_ext` と `observation.contact` として記録できるようにする | 模擬で npz とデータセットの特徴量を確かめる |
| 3．followerのモード | `robot.yaml` の `control` で，腕を電流制限つき位置制御（`current_position`，Mode 5）にする設定例を作る．`commission` でモードとCurrent Limitを書く | 実機：位置の追従と保持が今と同等であること．接触時に電流が上限で止まること |
| 4．`model_residual` | follower で保持電流を計測し，既存の回帰で `g_f(q)` を同定する道具を作る（`identify-gravity` を follower に対応させる）．`model_residual` 推定器を実装する | 実機：静止時と自由運動中の残差の大きさを記録する．既知の重りをかけたときの残差を確かめる |
| 5．leaderの逆送の項 | 電流制御の制御則に共通の部品として `feedback` を加える．gate，ramp，期限，接触のヒステリシス，`max_mA`，`kd` を入れる．status とトレースに `feedback_mA` と gate を出す | 模擬：期限切れ・HOLD・estopで ramp して0になる試験．実機：1関節だけ小さいゲインで有効にし，符号と振動のなさを確かめる |
| 6．グリッパー | トリガーを電流制御の新しい制御則（ばね＋減衰＋接触の項，factr2_next の `compute_gripper_feedback_torque` と同じ形）にする．followerグリッパーの電流（Mode 5，Current Limit 54 mA）を入力にする | 実機：物を握るとトリガーが重くなること．離すと戻ること |
| 7．NEXT | 自由運動のデータの記録手順（段階2のトレース），学習（`torch` を optional extra にする），推論ノード（robotの周期で動く）を作る．`model_residual` と同じ契約にする．重みとmanifestを「モデルの保存先」の形で書き，読み込み時に照合する | 実機：既知の重り・押し付けで `model_residual` と比べる．学習・推論のコマンドを docs に書く |
| 8．遅れ | feedback の遅れ（followerの状態の時刻からleaderが電流を書くまで）を status に出す．周期は§9を参照 | 実機：遅れの分布を記録する．ゲインの上限と合わせて docs に書く |
| 9．docs | 実装した段階ごとに，Controllers・Robots・Reference・Quick startを更新する．このページの該当部分は削る | docs の strict build が通る |

## 8．新しいロボットとleaderへの対応

follower として加える機体に必要なもの：

- `state` の `positions`，`velocities`，`currents_mA`（または外力），`target` を出すこと．`velocities` がない機体は，推定器で差分をとります．
- 外力の出し方を一つ選ぶこと．センサーがあれば `sensor`，なければ `model_residual` か `next` です．
- 位置制御の上で動くこと．トルク制御の機体でも，位置指令と `FollowerSafety` の範囲で動かせるなら使えます．

leader として加える機体に必要なもの：

- 力を返す関節を電流（トルク）で制御できること．位置しか出せない入力（VRなど）は，逆送なしで使います．
- 重力補償が使えること（`gravity_comp`，またはその機体の重力モデル）．
- controllerの `joints` で，leaderとfollowerの関節が1対1に対応すること．

運動学が違うleaderとfollower（関節の数や並びが違う）では，関節ごとの対応ができません．その場合は，手先の力 `F` を推定し，leaderで `Jᵀ F` に変換する必要があります．これは今回の範囲の外です．同じ契約（`residual` の代わりに手先の力を出す推定器）で後から足せるようにします．

対称型（robopy の `bilateral_joint`）も，leaderとfollowerに共通の制御則として後から加えられます．そのときは，followerの電流制御，両腕の重力モデル，トルク定数が必要です．

## 9．未解決の課題

- 遅れ：Rakuda2のバスは1 Mbpsで，状態の読み出しに4 ms（Fast Sync Read）かかります．これと書き込み前の待ちの省略により，leaderとfollowerの周期を60 Hzから120 Hzへ上げ，実機で確かめました（[設定](../reference/configuration.md) の「制御周期」）．逆送の経路はfollowerの1周期，推定，controller，leaderの1周期を通るので，遅れは数周期分（120 Hzで約20〜30 ms）と見込みます．FACTRの500 Hzよりは遅いので，gate，ramp，減衰，弱いゲインから始めます．通信速度を4 Mbpsへ上げると，さらに周期を上げられますが，全モーターのEEPROMを書き換える必要があり，今回は行っていません．
- 推定の精度：`model_residual` には摩擦と慣性が残ります．速く動かすと接触がなくても残差が出ます．接触の閾値で抑えますが，NEXTに置き換える前提です．
- 電流の上限：逆送の分だけleaderのCurrent Limitを上げる必要があります．ホストが止まったときに残る力が大きくなります．
- 方策での利用：外力を記録するところまでがroboloomの範囲です．FACTRのカリキュラムやFIRSTは学習側の課題です．
- 調査の範囲：FACTR 2の利用者実験の数値は図にしかなく，確かめていません．factr2_nextのREADMEと実装には食い違いがあります（例：READMEは重力補償を機能に挙げますが，配布設定では無効です）．
