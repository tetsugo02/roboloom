# YAM 実装の分析：安全guardと方策出力の滑らかな送信

作成日：2026-10-22．対象：`/home/tetsugo_local/workspace/YAM`（HEAD `839fb55`）．状態：調査メモ．roboloom への取り込み方針は §5 と [次期設計](../../dora-lerobot-next-design.md) の §11 にまとめる．

YAM は双腕 YAM arm（DM4340/4310 motor，CAN）で，teleop，data収集，MolmoAct-v2 の評価を行う実装である．本文の行番号は上記 HEAD のもので，pathは `gello_software/` を `gs/`，`i2rt/i2rt/` を `i2/` と略す．codeは読んだだけで，実機での挙動は確かめていない．数値は特記がない限り実運用の設定 `gs/configs/yam_left.yaml` の値である．

roboloom は複数の機体に対応する．このため YAM の工夫を次の三つに分けて読む．

- **汎用**：どの機体でも同じ形で使える考え方．roboloom の共通部分に入れる．
- **機体能力**：特定のhardwareの機能に依存する．roboloom では機体ごとに申告させ，起動時に確かめる．
- **運用上の対処**：YAM の単一process構成のために必要になったもの．roboloom の構成で不要になるか，形を変えて残るかを分けて考える．

## 1．構成とrate階層

| 層 | 周期 | 実体 |
| --- | --- | --- |
| camera | 30 fps，640×360 color | 別processの camera server（ZMQ REP/PUB） |
| 方策推論 | 1 回約 0.86 s（実機），背景threadでほぼ連続 | `gs/gello/rtc/engine.py` の `RTCInference` |
| 方策step | 10 Hz（学習dataは 30 Hz） | `ActionQueue` から 1 action を取り出す |
| chunk長 H | 30 actions | MolmoAct2 の flow-matching head |
| 制御loop | 10 Hz × 補間倍率 3 = 30 Hz | main thread，絶対deadline |
| i2rt server thread | 約 200 Hz（`update()` の後に 4 ms の sleep） | `i2/robots/motor_chain_robot.py:261-289` |
| CAN 送信 | 250 Hz | `i2/motor_drivers/dm_driver.py:492-547` |
| motor | onboard PD（MIT mode）．kp=[80,80,80,40,10,10]，kd=[5,5,5,1.5,1.5,1.5] | DM4340／DM4310 |

```text
RealSense ×3 ─► camera_server（別process）
                    │ 要求時だけ取得（timeout 500 ms，0.5 s より古いframeは拒否）
main thread 30 Hz ───────────────────────────────────────────────
  3 tick に 1 回：obs を取得 → engine.notify_observation（s_obs を記録）
                  → queue から 1 action → 補間器へ
  毎 tick：補間値 → apply_safety（NaN，gripper clip，±0.03 rad/tick）
          → floor guard → YAMRobot.command_joint_state
          （queue が空なら何も送らず，driverが最後の目標を保持）
RTCInference thread ───────────────────────────────────────────────
  queue 残り ≤ 22 なら：前chunkの s_obs 以降を prefix にして RTC 誘導付きで推論
                        → merge(chunk, start_step=s_obs)
i2rt：目標をlatch → 重力補償torque ×1.3 とgripper力制限を加える → 250 Hz CAN → motor PD
```

## 2．安全guard

### 2.1 層ごとの仕組み

| 層 | 仕組み | 違反時 | 分類 |
| --- | --- | --- | --- |
| motor firmware | 通信watchdog 400 ms（`i2/motor_config_tool/set_timeout.py`，flashに保存） | 指令が途絶えるとdampingになり脱力 | 機体能力 |
| motor firmware | 過電圧，過電流，過温度，過負荷，通信喪失のerror code（`i2/motor_drivers/utils.py:88-110`） | motor側で停止し，frameでcodeを返す | 機体能力 |
| CAN driver | 全frameのerror codeを検査（`dm_driver.py:530-536`） | 1 台でも異常ならchain全体を止める．その結果watchdogで脱力 | 汎用（方針）／機体能力（手段） |
| CAN driver | MIT fieldの飽和（±12.5 rad，速度，torque，kp 0–500，kd 0–5） | 範囲内に丸める | 機体能力 |
| i2rt robot | 指令を関節limit（±0.15 rad の余裕つき）で clip（`motor_chain_robot.py:413-430`） | clip | 汎用 |
| i2rt robot | 起動時と毎周期に実測位置をlimitと照合（さらに +0.1 rad，`:188-194`，`:348-350`） | 例外でchainを止め，脱力．原因の候補として零点ずれを表示 | 汎用 |
| i2rt robot | 重力補償torqueの妥当性．どれかが 20 Nm を超えたら異常（`:385-387`） | 脱力 | 機体能力（動力学model） |
| i2rt robot | gripper力制限．把持で詰まったと判定したら目標を書き換え，50 N 相当に抑える（`i2/robots/utils.py:250-331`） | 目標を緩める | 機体能力（torque推定） |
| gello env | `command_guard` hook．毎回の送信に `guard(実測, 指令)` をかける（`gs/gello/env.py:28-39`） | guardの実装による | 汎用 |
| gello env | camera障害を `CameraError` にまとめる（`env.py:174-191`） | 呼び出し側が回復可能な障害として扱う | 汎用 |
| floor guard | 全可動meshとgripper代理点が床面より下に行かないよう，関節空間の経路を 0.02 rad 刻みで検査（`gs/gello/utils/floor_guard.py:102-149`） | 二分探索で最後の安全点まで切り詰める．既に床下ならclearanceを減らす動きだけ許す | 汎用（機体modelが必要） |
| 制御loop（RTC） | `apply_safety`：NaN なら例外，gripperを [0,1] に clip，腕は**最後に送った値**から ±0.03 rad/tick に clamp（`gs/gello/rtc/safety.py:31-68`） | 例外，clip，clamp（clamp したかどうかを記録） | 汎用 |
| 制御loop（RTC） | chunkの形状と NaN を検査（`engine.py:511-522`）．一時的な失敗は最大 10 回まで再試行 | 致命的なら `shutdown_event` を立て，その後 park | 汎用 |
| 制御loop（収集） | 開始・再開時に leader と follower の関節差を関節ごとの上限 [0.25,0.25,0.25,0.4,0.4,0.8] rad と比べる（`control_utils.py:241-274`） | 開始を拒否し，差の表を表示 | 汎用（roboloom にも類似の仕組みがある） |
| 制御loop（収集） | 健全性検査：driverのthreadの生存，`running`，leader の読み出しが 0.25 s 以内か（`launch_yaml_collect_data.py:312-334`） | episodeを中断し，保存か破棄かを選ばせてから park→release | 汎用 |
| 制御loop（収集） | camera障害で一時停止．follower を保持し，leader も PWM 0.35 でその場に保持（`:886-1008`） | 復旧したら開始時と同じ検査を通して再開 | 汎用（leader の保持は機体能力） |
| session | 方策のloadとwarmup，GC の固定，互換性の検査を通電の**前**に行う | 起動前に終了 | 汎用 |
| session | 終了時は park → 「腕を支えて Enter」→ release → 重い変換処理，の順 | — | 汎用 |
| session | SIGTSTP を無視する（一時停止すると指令が止まるため）．2 回目の Ctrl-C でその場で脱力する | — | 汎用 |
| leader（GELLO） | 動かす量が 1.8 rad を超えるなら拒否．PWM と Profile Velocity に上限．保持目標を書いた後に読み戻して照合．追従遅れが 0.35 rad を超えたら全軸を解放 | 解放 | 機体能力（Dynamixel の leader） |

### 2.2 設計の要点

1. **故障の種類ごとに止め方を変えている．** firmwareとdriverの異常では脱力する．床面に近づいたら切り詰めるか保持する．camera障害では保持して一時停止する．方策の異常では保持し，その後 park する．「何が壊れたら，どの状態に移るか」を障害ごとに決めている．
2. **最終の clamp の基準を，最後に送った指令にしている．** 実測ではなく送信値を基準にするので，PD の追従遅れで clamp が連続することがない．clamp した tick には印を付けて記録し，その割合を後で評価する．
3. **重い処理は通電中にしない．** modelのload，GC，RealSense の再起動，dataset変換はどれも GIL を数百 ms 以上握る．これが 250 Hz のthreadを止め，400 ms のwatchdogで両腕が落ちるという事故が実際に起きていた．YAM の対処は二つある．処理を通電の前か解放の後に寄せることと，`gc.freeze()` である．
4. **人が関わる関門を置いている．** leader が離れていれば開始しない．解放前に確認を取る．guardの無効化には明示的なflagが要る．設定の確認には `start_joints_confirmed: true` のような申告を要求する．
5. **障害を前提に，片付けの順序を組んでいる．** 腕は組み立て直後に登録するので，2 本目の構築に失敗しても 1 本目を解放できる．推論threadを先に止めてから park する．

### 2.3 弱点（codeから読み取れるもの．実機では未確認）

- watchdogのregisterを実行時に読み戻していない．0（無効）のままのmotorがあると，「指令を止めれば脱力する」という前提が黙って崩れる．終了時に motor-off frameも送らない．
- driverのthreadが死んでも，収集以外の起動scriptは気づかない．cacheされた状態を読み，死んだbufferに書き込み続ける．
- 応答しないmotorがあると，再試行のため CAN threadが最大で約 3 s 止まる．watchdogより長いので，同じbusの他のmotorも落ちる．
- `clip_motor_torque` の既定値が `inf` で，torque上限が実質的に効いていない．温度は表示するだけで，出力を下げたり止めたりしない．
- 起動直後は zero-gravity mode（kp=0）で，重力補償は 1.3 倍の過補償になっている．最初の位置指令までの間に腕が浮いたり流れたりしうる．
- floor guard は MolmoAct の評価scriptでしか使っていない．収集，teleop，再生では効いていない．
- 同期評価の HTTP 推論 `requests.post` にtimeoutがない（`gs/experiments/molmoact.py:210`）．
- portが使用中のとき，`fuser -k` で使用中のprocessを殺す（`gs/gello/dynamixel/driver.py`）．別の収集processを殺すと，その腕が落ちる．
- 記録つき RTC 評価で `saver.add_step` に必須引数の `action` を渡していない（`gs/experiments/launch_yaml_eval_molmoact_rtc.py:441`，`gs/gello/utils/eval_utils.py:98-104`）．2 回目の方策 tick で `TypeError` になるはずである．testの代役objectは引数 2 個なので検出していない．loop版は記録しないので影響しない．

## 3．方策出力を滑らかに送る工夫

### 3.1 非同期推論と置換式の ActionQueue

同期式では，推論している 0.6〜0.9 s の間armが止まり，chunkの境目ごとに停止する．YAM の RTC 経路では，推論を背景threadで回し，制御loopは前のchunkを実行し続ける．

- queue の残りが `queue_threshold=22` 以下になったら次の推論を始める．merge の直後で残りが約 20 なので，推論はほぼ連続して回る．
- ActionQueue は**置換式**である．新しいchunkが来たら，前のchunkの残りは捨てる．
- **step clock**：queue は取り出した回数 `_steps` を数える．観測を通知した時点の回数を `s_obs` として記録し，merge では `_steps − s_obs` 個を正確に捨てる（`gs/gello/rtc/action_queue.py:141-156`，`:221-228`）．経過時間からではなく，**実際に消費した数**から捨てる量を決める．
- この時刻合わせの修正（`1475441`）の前は，prefix が 1 stepずれていた．計画が 1 action 後戻りして止まって見える症状が出ていた．実測では，継ぎ目の段差が 0.111 → 0.022 rad，clamp された tick が 10% → 3% に減った．
- **epoch**：`reset()` で queue を空にしてepochを進める．resetより前に始まった推論の結果は，merge の時点で捨てる（`engine.py:238-244`，`:419-431`）．
- 指示文を変えても queue は空にしない．空にすると推論 1 回分止まるので，次のchunkから効かせる．

### 3.2 遅延の推定

- 遅延は観測の通知から merge までを測る．`d = ceil(L × fps)` で，単位は方策stepである．
- 誘導に使う d は，直近 100 回の**最大値**から求め，`execution_horizon` を上限にする．最初の 1 回（cold start）は除く．
- 実測では，実際に消費した d が約 9.5 であるのに対し，推定は約 13.6 で過大だった．p95 にする案が文書で検討されているが，実施していない．
- 起動時に，設定が方策の出力と矛盾しないかを検査する（`launch_yaml_eval_molmoact_rtc.py:124-172`）．`eh > H`，`q ≥ H`，`d ≥ H` はerror，`q < d`（queue が枯れる），`d > eh`（重みが 1 から 0 に段差で落ちる），`q < eh` は警告である．

### 3.3 RTC 誘導（chunk間の inpainting）

- prefix は，前chunkのうち s_obs 以降の**正規化された**行である．長さが足りない分は末尾の action を繰り返して埋める．0 で埋めると，正規化空間では「datasetの平均」を意味してしまうからである．
- 正規化が上下限つきの方式なら，prefix を [−1,1] に clip する．逆正規化で clip されたものが実際に実行された値だからである．
- 重み：`i < d` なら 1，`d ≤ i < eh` なら線形に 1 から 0 へ下げ，`i ≥ eh` なら 0（`guidance.py:99-127`）．
- 誘導つき速度は閉じた式で計算する：`x̂₁ = x_t + (1−t)v`，`v' = v + gw(t)·(prev − x̂₁)⊙w`．VJP を使わないので，autograd の追加costがない．
- gain `gw` は τ に対して U 字型で，上限 `β = min(max_guidance_weight, num_steps)` で抑える．1 stepの補正が 1 を超えると Euler 更新が目標を飛び越えるためである．
- 調整の経緯：
  - β を 10 から 5 に下げた．実行された action の 48% が w=1，つまり前の計画をそのまま写したものだったからである．
  - eh を 14 から 20 に上げた．d が eh に張り付くと，重みが 0 と 1 の中間になる区間がなくなり，境目に段差が出たからである．代わりに反応性が下がる．
- CUDA graph は無効にする．graph を再生すると，flow loop の差し替えを素通りしてしまう．
- 最初のchunkは prefix なしで生成する．

### 3.4 送信rateへの補間

- `ActionInterpolator` は，方策の action 1 個から `prev + (i/N)(a − prev)` を N−1 個，最後に `a` そのものを出す．N=3 である（`gs/gello/rtc/interpolator.py`）．
- `prev` は merge をまたいでも持ち越す．このため継ぎ目の段差も N tick に分散する．
- driver側には補間も速度feedforwardもない．約 33 ms のzero-order holdを，motor内の PD が滑らかにしている．速度に比例した追従遅れがあり，指令は実測より平均 0.04〜0.11 rad 先行していた．

### 3.5 固定周期loopと停止の扱い

- 絶対deadline方式で，次の期限を `deadline += period` で決める．1 周期を超えて遅れたら `deadline = now` に戻し，取り返そうとして連続送信しない．
- **queue が空になったら何も送らない．** driverが最後の目標を保持するので，armはその場で止まる．空になった tick と，最初の action を待つ tick は分けて数える．
- 世代 2 の GC が約 4 s ごとに約 106 ms 止まっていた．overrun はすべてこれが原因で，CAN threadも一緒に止まっていた．対処として，通電の前に `gc.collect(); gc.freeze()` を行う．GC の発生は記録に残す．
- 方策の入力にする状態は `observation_source: command` で，最後の指令を使う．学習dataが指令値を状態として記録していたからで，measured にすると精度が落ちた（`d946833`）．
- 開始時：開始姿勢を保持したまま最初のchunkを待つ（約 1 s）．最初の action は補間せず，clamp だけで出す．loop版は，**実測の**関節が開始姿勢の 0.05 rad 以内に入ってから次の指示を受け付ける．
- 終了時：減速の区間はない．最後の指令で止まる．

### 3.6 滑らかさの測り方

`rtc_trace.npz` と `gs/experiments/rtc_trace_report.py` は次を出す．滑らかさを主観でなく数値で議論するための道具で，roboloom の測定項目にも使える．

- tick 周期の分布，overrun と GC の重なり，overrun の間隔の変動係数（周期的なら GC を疑う）．
- 追従誤差 `|measured − sent|`，速度のpeak．
- **進み比** `(v_i·v_{i−1})/|v_{i−1}|²`．+1 は等速，負は計画の後戻りを表す．
- 継ぎ目と index ごとの段差，clamp の回数，queue が空になった回数．
- 実行された action の重みの内訳（w=1，中間，w=0）．d が eh に張り付いた割合．

`rtc_offline_check.py` はrobotなしで，2 つの観測から作ったchunkの prefix の一致度と継ぎ目の段差を測る．

### 3.7 同期経路との比較

同期評価の `dynamic_smoothing` は，1 action を `max(腕Δ/0.1, gripperΔ/0.02)` 個（上限 100）の直線substepに分け，30 Hz で送る．速度は実質的に閾値で抑えられ，推論中は静止する．RTC は止まらないが，追従遅れが大きく，それが精度低下の一因と見られている．

## 4．分類の要約

| 工夫 | 汎用か | 備考 |
| --- | --- | --- |
| step clock と s_obs による時刻合わせ，置換式 queue，epoch | 汎用 | chunkを出す方策なら全般に使える |
| RTC 誘導 | 方策の能力 | flow-matching や拡散の推論loopに手を入れられる方策に限る |
| 補間（prev を持ち越す） | 汎用 | 送信rateは機体で異なる |
| 最後に送った値を基準にした変化量の clamp と記録 | 汎用 | 上限は rad/s などの物理量で持つ |
| queue が空なら保持 | 汎用（保持の手段は機体能力） | 位置制御の機体なら最後の目標を保持できる．速度制御では 0 速度を送る |
| 起動前の互換性検査，重い処理を通電前に寄せる | 汎用 | |
| park → 確認 → release | 汎用（release の手段は機体能力） | YAM はwatchdog任せ．Dynamixel はtorque offを明示的に送る必要がある |
| 障害ごとの遷移（脱力，保持，一時停止） | 汎用（どれを選べるかは機体能力） | brakeのない重い腕で脱力を選ぶと落下する |
| floor guard（運動学的な経路検査） | 汎用の枠組み，機体modelが必要 | modelがない機体では使えない |
| 通信watchdog，firmwareのerror code，MIT modeの PD，kp/kd，重力補償，gripper力制限 | 機体能力 | DM motor固有のもの |
| leader の PWM 駆動による姿勢合わせ | 機体能力 | Dynamixel の leader 固有 |
| GC の固定，cameraの別process化，通電中の重い処理の回避 | 運用上の対処 | dora-rs のnode分割に置き換える（§5.6）．robot node内の GC と資源の競合は残る |

## 5．roboloom への取り込み方針

### 5.1 機体能力の申告

`Robot` に，機体が持つ機能を宣言する仕組み（`capabilities`）を加える．robot nodeは起動時にこれを読み，安全上必要な能力がなければ起動を拒否するか，明示した代わりの動作を選ぶ．能力が「あるはず」として扱う箇所を作らない．

| 能力 | 例 | 使う箇所 |
| --- | --- | --- |
| `hardware_watchdog_ms` | YAM：400 ms，Dynamixel：なし | 起動時にregisterを読み戻して照合する．なければ robot nodeが明示的に脱力するか保持する |
| `release` | torque off指令，watchdog任せ，brake | park → release の手段 |
| `safe_stop` | `hold`，`limp`，`brake` | 障害時の遷移先．重力で落ちる機体では `limp` を選べなくする |
| `fault_codes` | DM のerror code，Dynamixel の Hardware Error Status | 毎周期検査して FAULT をlatchする |
| `effort` / `temperature` | 電流，torque推定，温度 | gripper詰まりの制限，温度での出力低下や停止 |
| `onboard_pd` / `velocity_feedforward` | MIT mode，xArm の servo mode | 補間器が出す速度を送るかどうか |
| `kinematic_model` | URDF や MJCF | floor guard，作業空間の制限 |

既存の Rakuda の Dynamixel 実装では，watchdogがない前提で HOLD と停止の意味を決める．YAM の「止めれば脱力する」をそのまま移さない．

### 5.2 安全判定（`FollowerSafety`）の改修候補

現行の `FollowerSafety.tick` は，範囲外や `max_step` 超過の指令を**拒否して HOLD** にする．leader 操作なら妥当だが，方策の出力ではchunkの継ぎ目の小さな段差でも停止し，ガクつきの原因になる．YAM の運用をふまえ，二段階に分ける．

1. **soft clamp**：最後に送った値から，`max_speed`（rad/s やcount/s）× 実際の tick 間隔までに切り詰めて送る．`clamped` の印と，希望値・送信値の両方を記録する．
2. **hard reject**：NaN，次元違い，期限切れ，関節範囲外，明らかに大きな飛び（soft の上限の数倍）．これまで通り HOLD にし，必要なら FAULT をlatchする．

上限は tick あたりの値ではなく物理量で持つ．制御周期を変えても意味が変わらないようにするためである．

### 5.3 方策用の経路

方策の出力は `ActionChunk` として扱い，[次期設計](../../dora-lerobot-next-design.md) §4 の案を具体化する．

- `policy-*` nodeがchunkを出し，`controller-policy` が queue，step clock，補間を持つ．YAM の `s_obs`，`start_step`，epochの考え方をそのまま使う．時刻は経過時間でなく消費数で揃える．
- RTC 誘導は方策の能力として扱う．推論loopに手を入れられない方策では，誘導なしの置換式 queue と補間だけを使う．
- 補間の結果を毎 tick dora で送るか，時刻つきの短い経由点列を robot nodeに渡して robot nodeが補間するかは，dora 越しのjitterを測って決める．後者なら IPC の揺れが送信周期に響かないが，robot nodeの責務が増える．
- queue が空になったら何も送らず，robot nodeが期限切れとして保持する．空になった tick を数えて記録する．
- 推論の失敗，形状の不正，NaN はchunkの段階で拒否する．続いたら session に停止を求める．

### 5.4 sessionと記録

- 通電の前に，方策nodeのloadとwarmup，方策出力と設定の互換性検査を済ませる．session は，方策nodeの準備完了を受け取ってから robot nodeに通電を指示する（§5.6）．
- 終了は park → 確認 → release の順にし，release の手段は機体能力から選ぶ．
- `observation.state` には実測と最後の指令の両方を保存する．方策にどちらを入力するかは設定で選び，metadataに残す．YAM では，学習時と評価時でこの意味が食い違ったことが精度に効いた．
- recorder の測定項目に，YAM の trace にある指標を加える：tick 周期，clamp の割合，queue が空になった割合，継ぎ目の段差，進み比，追従誤差．

### 5.6 GIL と GC への対処を dora-rs の構成に置き換える

YAM は推論，cameraの一部，記録，CAN の送信threadを同じ Python processに置いている．このため，GIL を長く握る処理が 250 Hz のthreadを止め，watchdogで腕が落ちた．YAM の対処は，処理の時期をずらすこと（通電前，解放後），`gc.freeze()`，cameraの別process化である．

roboloom では，[次期設計](../../dora-lerobot-next-design.md) §3 の方針どおり，dora-rs のnodeとしてprocessを分ける．Python nodeはそれぞれ別のinterpreterで動くので，GIL はnodeごとに独立する．YAM の各問題を次のように置き換える．

| YAM の問題と対処 | roboloom（dora-rs）での扱い | 残るもの・確かめること |
| --- | --- | --- |
| modelのloadと推論が GIL を握り，CAN threadを止める．通電前にloadする | `policy-*` nodeを別processにする．robot nodeの GIL には影響しない | GPU と CPU の競合．通電の前に方策nodeが準備完了を返す手順は残す（起動直後の推論の遅れで queue が枯れないようにするため） |
| RealSense の再起動が GIL を握る．cameraを別processの server にする | `sensor-*` nodeとして最初から分ける．再起動や USB resetもそのnode内で行う | USB 帯域の共有．reset中は欠損として記録する |
| dataset変換と PNG 保存が GIL を握る．解放後に変換し，保存threadを nice 10 にする | recorder nodeを別processにする．変換はsession後か別jobにする | diskと CPU の競合．収録中の制御周期への影響を測る（TODO 段階 3） |
| 世代 2 の GC が約 4 s ごとに約 106 ms 止まる．`gc.freeze()` で抑える | robot node内の問題として残る．robot nodeは毎周期の割り当てを減らし，起動後に `gc.freeze()` するか，世代の閾値を調整する．GC の発生を記録する | robot nodeの tick 周期の p99 と最大で効果を確かめる |
| CAN 送信を Python threadで回す | robot nodeの中に閉じる．watchdogを持つ機体では，robot nodeが止まっても機体側で脱力する．持たない機体では，robot nodeの停止が保持のままになる | 機体能力 `hardware_watchdog_ms` で分ける（§5.1）．robot nodeの周期を timer で駆動するかnode内で待つかは実測で決める |
| 30 Hz の指令をmain threadから直接driverに渡す | controller から robot nodeへ dora のmessageで渡す．robot nodeは最新の有効な指令だけを使う | dora 越しの遅延とjitter．入力の `queue_size` を 1 にして古い指令を溜めない．経由点列を送る案（§5.3）の判断材料にする |
| 方策threadの例外を `shutdown_event` で制御loopに伝える | 方策nodeは異常を session に送る．robot nodeは指令が期限切れになれば単独で保持に移る | nodeが死んだときの検出．dora の自動再起動は使わない（次期設計 §5） |
| 画像を 2 MB の pickle で同期 REQ する | 画像は dora のmessage（Arrow，共有memory）で方策nodeに直接送る．robot nodeは画像を受け取らない | 方策nodeでの画像の鮮度（取得時刻）を記録する |

dora でprocessを分けても，CPU，GPU，USB，memory，diskは共有される．「別processだから周期が乱れない」とはみなさず，YAM で効いた項目（GC，推論中，camera復旧中，記録中）ごとに robot nodeの tick 周期を測る．

### 5.7 取り込まないもの

- `fuser -k` や `sudo chmod` による機器の奪取．使用中なら起動を拒否する．
- timeoutのない推論呼び出し．
- torque上限 `inf` を既定値にすること．
- YAM の数値（0.03 rad/tick，kp/kd，重力補償 1.3 倍，50 N など）．機体ごとに実測して決める．

## 6．実装時の設計上の注意

1. 機能は「汎用の契約」と「機体能力」に分けて実装する．robot node，controller，方策nodeの共通部分に，特定のmotorのregister，frame形式，gainを書かない．
2. 能力に依存する安全機能は，起動時に申告と実機の値（読み戻し）の両方で確かめる．ない場合の動作を明示的に選び，黙って弱めない．
3. 上限と期限は物理量と時間で持ち，tick あたりの値は実際の周期から計算する．
4. 安全判定の結果（clamp，reject，HOLD，FAULT）はすべて記録に残し，滑らかさと安全を数値で評価できるようにする．
5. 障害ごとに遷移先を決め，機体の機構（重力負荷，brakeの有無）で選べる遷移を制限する．
6. 新しい機体を追加するときは，能力の表を埋め，§5.1 の照合と異常注入の試験を通してから実機で動かす．

## 参考にした YAM のfile

- 安全：`i2/robots/motor_chain_robot.py`，`i2/robots/get_robot.py`，`i2/robots/utils.py`，`i2/motor_drivers/dm_driver.py`，`i2/motor_config_tool/set_timeout.py`，`gs/gello/env.py`，`gs/gello/robots/yam.py`，`gs/gello/utils/floor_guard.py`，`gs/gello/rtc/safety.py`，`gs/gello/utils/control_utils.py`，`gs/experiments/launch_yaml_collect_data.py`，`docs/floor_guard.md`．
- 滑らかさ：`gs/gello/rtc/`（`action_queue.py`，`engine.py`，`guidance.py`，`flow_loop.py`，`interpolator.py`），`gs/experiments/launch_yaml_eval_molmoact_rtc.py`，`gs/experiments/launch_yaml_eval_molmoact.py`，`gs/experiments/rtc_trace_report.py`，`docs/rtc_tradeoffs.md`，`docs/yam_rtc_eval.md`，`gs/configs/rtc_variants/README.md`．
- 全体：`CLAUDE.md`．`docs/yam_rtc_eval.md` の表はcodeの既定値（fps 30，eh 10，β 10，clamp 0.05）で，実運用の値（fps 10×3，eh 20，β 5，clamp 0.03）とは違う．
