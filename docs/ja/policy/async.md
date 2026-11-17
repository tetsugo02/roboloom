# 非同期の推論と補間

方策nodeは，`rate_hz` の周期で行動を1手ずつ取り出し，その間を補間してfollowerへ送ります（[周期と手数](run.md#rate-and-steps)）．このページは，推論を指令と並行して走らせる方法と，補間の方法を説明します．keyの一覧は [方策の設定](../reference/configuration/policy.md#interpolation) にあります．

## 非同期の推論 <span class="status status--mock">模擬のみ</span> { #asynchronous-inference }

推論の遅いmodelでは，まとめた行動の境目ごとに，`infer` の間followerが止まります．`inference: async` は `infer` を別threadで走らせ，その間も並んでいる行動を送り続けます．

```yaml
inference: async     # 既定は sync
replan_at: auto      # 残りがこの手数になったら次の推論を始める
action_horizon: 16
```

- 並んでいる行動が `replan_at` 手になったら，次の推論を始めます（`auto` は `action_horizon` の半分．数を書くなら `action_horizon` 未満）．残りの行動で推論の時間をまかなえるように決めます（`replan_at / rate_hz` 秒）．
- 新しい行動の列は，先頭のd手を捨ててから，並んでいる行動と入れ替えます．dは，その推論に使った観測のあとに実行した手数です．行動はそれぞれ本来の時刻に実行されます（LeRobotの非同期のrolloutと同じ考え方です）．controllerの行の `dropped` がdです．
- 行動の列が届く前に並んでいる行動がなくなると，指令を送らず，followerは保持します（`late_inference`）．`replan_at` か `action_horizon` を増やしてください．episodeの始めは，最初の列が届くまで `waiting_inference` です．
- teleopへの切り替え，`stop`，sensorの値が古くなったときは，走っている推論の結果を捨てます．`policy.reset()` はその推論が戻るまで待つので，`reset` と `infer` が重なることはありません．
- `infer` の例外は，同期のときと同じくepisodeを止めます（[episodeの途中で方策が失敗したとき](custom.md#failures)）．
- 方策は，観測した時刻から始まる行動の列を返すものとして扱います．呼ばれるたびに続きを返す方策（記録の再生など）では，先頭を捨てると行動が飛びます．そういう方策は，`bind(spec)` で `spec.inference` を見て `async` を断ってください．
- 新しい列と古い列は混ぜません．real-time chunking（RTC．flow matchingのmodelに古い列を条件として渡す方法）は実装していません．続けて返す列が大きく違う方策では，入れ替えのときに目標が飛びます（`max_speed` の範囲内）．

## 行動の補間 { #interpolation }

方策nodeは `rate_hz × N`（N は `interpolation_multiplier`）の周期で指令を送ります．行動はN回の指令ごとに1手取り出し，その間は1つ前の行動から今の行動までの直線をN等分した目標を送ります．行動の時間の間隔は学習時のまま，followerには細かい目標が届きます．

N を書かなければ（または `auto`），`rate_hz × N` が整数のHzで，いちばん遅いfollowerの `control_hz` 以下になる最大のNを使います．followerが受け取れる限り細かく指令を送ります．

| `rate_hz` | followerの `control_hz` | 計算されるN | 指令の周期 |
| --- | --- | --- | --- |
| 15 | 120（Rakuda2） | 8 | 120 Hz |
| 5 | 120 | 24 | 120 Hz |
| 7.5 | 120 | 16 | 120 Hz |
| 30 | 30 | 1（補間しない） | 30 Hz |

数を書くと，その値を使います．`1` は補間せず，行動を1手ずつ送ります．

```yaml
rate_hz: 5                    # 5 Hz で学習した方策
interpolation_multiplier: 12  # 指令を 60 Hz に抑える（省略すると 24，120 Hz）
```

- LeRobotのrollout（`lerobot.utils.action_interpolator.ActionInterpolator` の `interpolation_multiplier`）と同じ方法です．違いは最初の1手だけです．LeRobotは最初の行動をそのまま送りますが，roboloomはfollowerが保持している目標から最初の行動まで補間します．
- followerが各行動に着くのは，その行動が出てから1手分（`1/rate_hz`，5 Hzなら200 ms）あとです．
- 数を書くときは，`rate_hz × N` を整数のHzで，どのfollowerの `control_hz` 以下にします．それ以外は読み込み時に拒否します．`rate_hz` が整数のHzにできない値（7.33 など）のときは，計算されるNは1です．
- 使っているNは，操作画面の方策の行に `interpolation` として出ます．
- 評価で記録するdatasetの `action` は，followerに実際に送った補間後の目標です．
- まとめた行動の境目では，`infer` の間だけ補間も止まります．次の行動は，止まる前に着いた行動から続けます．
- 送る目標は，followerが保持している目標から `max_speed` の分までに切り詰め，`FollowerSafety` が可動域と期限を検査します．遠隔操作と同じです．

### 直線の代わりに滑らかな曲線を使う（`interpolation: pchip`） <span class="status status--mock">模擬のみ</span> { #pchip }

直線では，行動のたびに速度が急に変わります．`interpolation: pchip` は，同じ行動を通る単調な3次曲線（Fritsch–Carlson）を送ります．

```yaml
interpolation: pchip   # 既定は linear
```

- 目標は，どの行動もその本来の時刻に通ります．直線に対する遅れは増えません（low-pass filterでは遅れます）．
- 隣り合う2つの行動の間では，目標はその範囲から出ません．方策の行動に雑音があっても，行き過ぎません．
- 行動の時刻で速度が連続します．ただし，先に読んだ次の行動が，実際に次に実行する行動と同じ場合に限ります（下の項目）．保持している姿勢からの最初の行動は，速度0から始まります．2つの行動の中間では，速度が直線の1.5倍まで上がることがあります．`max_speed` の制限は同じく効きます．
- 曲線には，向かっている行動の次の行動が要ります．並んでいる行動から取ります．まとめた行動の最後の手（同期の推論，または `action_horizon: 1`）には次がないので，その区間は直線の傾きで終わります．`inference: async` なら，並んでいる行動がなくなる前に次の列が届くのがふつうです．
- 速度が連続しない場合が2つあります．1つは，次の行動を読めなかった区間のあとで，次の行動が逆向きか，大きく違う場合です（まとめた行動の境目，`action_horizon: 1`）．もう1つは，`inference: async` で並んでいる行動が入れ替わり，先に読んだ次の行動が変わった場合です．どちらでも，次の区間の始めの傾きを範囲に収め直すので，行き過ぎはしませんが，その行動の時刻で速度が飛びます．
- 既定は `linear` のままです．LeRobotと同じ方法で，これまでの確認はこちらで行っています．どちらも実機で比べてはいません．記録したepisodeをそれぞれで再生し（[記録を再生する](evaluation.md#replaying-a-recording)），記録された `observation.state` を比べてください．
