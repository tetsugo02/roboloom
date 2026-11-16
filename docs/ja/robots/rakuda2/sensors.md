# Rakuda2のセンサー

Rakuda2のテンプレートが持つセンサーと，それを有効にするオプションです．センサーごとの設定は [Sensors](../../sensors/index.md) にあります．

| センサー | ノード名 | 設定 | 有効にする方法 | 状態 |
| --- | --- | --- | --- | --- |
| [RealSense](../../sensors/realsense.md) | `camera` | `nodes/camera.yaml` | 既定で有効 | <span class="status status--verified">実機検証済み</span> |
| [DIGIT](../../sensors/digit.md) | `digit_left`，`digit_right` | `nodes/digit_left.yaml`，`nodes/digit_right.yaml` | オプション `digit` | <span class="status status--verified">実機検証済み</span> |
| [音声](../../sensors/audio.md) | `audio` | `nodes/audio.yaml` | `--sensors` で選ぶ（既定は無効） | <span class="status status--dev">開発中</span> |

- センサーのシリアル番号は実機に合わせて設定します．センサー名はデータセットのfeature名になります（`observation.images.camera` など）．
- 各センサーには，`nodes/recorder.yaml` の `max_age_ms` に同じ名前の項目が要ります（[Recorderの設定](../../sensors/index.md#recorder)）．

## 組み合わせ { #combinations }

| 有効なオプション | 記録するセンサー | データセット名 |
| --- | --- | --- |
| なし | RealSense | `local/rakuda2` |
| `digit` | RealSense＋左右DIGIT | `local/rakuda2-digit` |
| `gravity`，`digit` | RealSense＋左右DIGIT | `local/rakuda2-digit` |
| `digit`，`policy` | RealSense＋左右DIGIT | `local/rakuda2-digit-eval` |

- 画像のfeatureが変わるので，`digit` の有無でデータセットが分かれます．RealSenseだけのデータセットへ，DIGITのエピソードは追記しません．
- `digit` を有効にしても，方策の入力は変わりません．DIGITを方策に渡すときは，`nodes/policy.yaml` の `observe` を `[camera, digit_left, digit_right]` にします（[観測を選ぶ](../../policy/custom.md#observations)）．
- オプションの全体は [起動オプションと組み合わせ](index.md#options) にあります．

## センサーを選ぶ { #sensor-selection }

<span class="status status--mock">模擬のみ</span>

起動・記録するセンサー（`sensors`）と，方策が観測するセンサー（`observe`）は，起動ごとに別々に選べます．`None` は設定の既定，`[]` は選択なしです．フォロワの状態は常に渡します．

```bash
uv run roboloom run --sensors camera,audio
uv run roboloom infer --seconds 20 --sensors camera,audio --observe camera
```

```python
with Session.launch(
    "rakuda2",
    options=["policy"],
    sensors=["camera", "audio"],
    observe=["camera"],
    policy="my_lab.policies:load",
) as session:
    session.wait_ready()
    session.record("pick", seconds=20)
```

- 空の選択は `--sensors "" --observe ""` です．ランチャーには，起動するセンサーと方策の観測のチェック欄が別々にあり，前回の選択を保存します．
- 選ばなかったセンサーのYAMLは読み込みません．起動していないセンサーを観測に指定するとエラーです．
- 左右のDIGITを含め，オプションで追加されるセンサーも個別に選べます．選択はオプションを適用したあとに決まります．
- 任意のセンサーは `config.yaml` で `{file: nodes/audio.yaml, default: false}` と宣言します．文字列のパスは既定で有効です．
- `observe` に含めないセンサーも，起動すれば記録します．
- `RobotConfig` を渡すときは，`load_config(..., sensors=[...], observe=[...])` で選択を確定してください．
- 書き方の規則は [センサー選択](../../reference/configuration/sensors.md#sensor-selection) にあります．
