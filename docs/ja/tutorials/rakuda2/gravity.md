# Rakuda2：重力補償

<span class="status status--verified">実機検証済み</span>

- **目的**：leaderの腕の零点・方向・可動域を測り，重力modelを同定して，重力補償付きleader（option `gravity`）を調整する．
- **前提**：[Rakuda2：機体設定と読み取り確認](setup.md) が済んでいる．腕を支える人がいる．
- **所要**：1〜2時間．
- **結果**：`calibration/` に `gravity_<side>.yaml`，`travel_<side>.yaml`，`gravity_tuning_<side>.yaml` ができ，`--with gravity` で起動できる．

## 1. 重力補償用の零点・方向・可動域を設定

このページの操作は，dataflowを止め，他のtoolがleaderのbusを開いていない状態で行います．腕を支持し，torque offを確認してください．左右のcalibration YAMLのmotor IDとURDF関節の対応を確認し，URDF零姿勢に置いて測定します．

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_right.yaml
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_left.yaml
```

保存された `zero` と各関節の `direction`（`1` または `-1`）を確認し，対応・零点・方向を検証できたら各fileの `confirmed: true` を設定します．templateの零点や符号を未確認のまま承認しないでください．

脱力したleaderを手でゆっくり動かし，左右の可動域を測定します．

```bash
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_left.yaml --out .roboloom/rakuda2/calibration/travel_left.yaml
```

この操作はbusから位置を読むだけですが，結果をYAMLに保存します．この範囲はleaderの暴走検知に使い，followerの安全限界の代用にはしません．

## 2. 重力modelを同定

`identify-gravity --collect` は保持電流を測るため **motorに通電** します．周囲と支持方法を確認し，画面の姿勢配置・手を離す指示に従います．

```bash
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_left.yaml --out .roboloom/rakuda2/calibration/gravity_left.yaml --collect
```

通電の前に，続けてよいかを確認します．

出力の適合度と警告を確認します．関節方向や計測品質が不適切だと保存を拒否します．原因を直して再計測し，未生成のmodelで次へ進まないでください．設定・測定した姿勢によって誤差が残るため，次にgainとholdを調整します．

## 3. 重力補償modeを設定・調整

重力補償はoption `gravity` です．有効にすると，leaderが `nodes/leader.yaml` から `nodes/leader_gravity.yaml` に置き換わります．`nodes/leader_gravity.yaml` が左右の `gravity_<side>.yaml`，`travel_<side>.yaml`，`gravity_tuning_<side>.yaml` を参照します．電流上限・watchdog・可動域を確認した上で設定を検証し，EEPROMの変更を確認します．

```bash
uv run roboloom validate --with gravity
uv run roboloom commission leader --with gravity
uv run roboloom tune-gravity leader right_arm --with gravity
uv run roboloom tune-gravity leader left_arm --with gravity
```

`gravity` の有無でleaderのOperating Modeが変わります．このあと `gravity` なしで起動すると，CLIは起動前にEEPROMの差分を表示し，確認してから書き戻します．

調整開始時は両腕を支えます．調整対象でない側は脱力しています．

| 操作 | 内容 |
| --- | --- |
| `↑` / `↓` | 関節を選ぶ |
| `[` / `]` | 重さを打ち消すgainを下げる / 上げる |
| `-` / `=` | 動き始めの保持力 `hold_mA` を下げる / 上げる |
| `0` | 選択関節の重力補償を切り替えて比較する |
| `s` | 調整値を保存する |
| `q` | 終了する |

腕が下がるならgainを上げ，上がるなら下げます．動かし始めが重い場合はholdを下げます．電流が上限に張り付く場合は調整を止めて設定を見直します．詳細と制約は [Gravity tuning](../../explanation/gravity-compensation.md) にあります．Current Limitとwatchdogは別の保護であり，XC330のwatchdog作動だけで電流がゼロになるとは想定しません．

## 次へ

- 重力補償付きleaderで収集する：[Rakuda2：teleopで収集](collect.md)
- 式と調整値の意味：[重力補償の調整](../../explanation/gravity-compensation.md)
