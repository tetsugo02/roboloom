# Rakuda2のsensor

Rakuda2のtemplateが持つsensorと，それを有効にするoptionです．sensorごとの設定は [Sensors](../../sensors/index.md) にあります．

| sensor | node名 | 設定 | 有効にする方法 | 状態 |
| --- | --- | --- | --- | --- |
| [RealSense](../../sensors/realsense.md) | `camera` | `nodes/camera.yaml` | 既定で有効 | <span class="status status--verified">実機検証済み</span> |
| [DIGIT](../../sensors/digit.md) | `digit_left`，`digit_right` | `nodes/digit_left.yaml`，`nodes/digit_right.yaml` | option `digit` | <span class="status status--verified">実機検証済み</span> |
| [音声](../../sensors/audio.md) | `audio` | `nodes/audio.yaml` | `--sensors` で選ぶ（既定は無効） | <span class="status status--dev">開発中</span> |

- sensorのserial番号は実機に合わせて設定します．sensor名はdatasetのfeature名になります（`observation.images.camera` など）．
- 各sensorには，`nodes/recorder.yaml` の `max_age_ms` に同じ名前の項目が要ります（[Recorderの設定](../../sensors/index.md#recorder)）．

## 組み合わせ { #combinations }

| 有効なoption | 記録するsensor | dataset名 |
| --- | --- | --- |
| なし | RealSense | `local/rakuda2` |
| `digit` | RealSense＋左右DIGIT | `local/rakuda2-digit` |
| `gravity`，`digit` | RealSense＋左右DIGIT | `local/rakuda2-digit` |
| `digit`，`policy` | RealSense＋左右DIGIT | `local/rakuda2-digit-eval` |

- 画像のfeatureが変わるので，`digit` の有無でdatasetが分かれます．RealSenseだけのdatasetへ，DIGITのepisodeは追記しません．
- `digit` を有効にしても，方策の入力は変わりません．DIGITを方策に渡すときは，`nodes/policy.yaml` の `observe` を `[camera, digit_left, digit_right]` にします（[観測を選ぶ](../../policy/custom.md#observations)）．
- optionの全体は [起動optionと組み合わせ](index.md#options) にあります．

## sensorを選ぶ { #sensor-selection }

<span class="status status--mock">模擬のみ</span>

起動・記録するsensor（`sensors`）と，方策が観測するsensor（`observe`）は，起動ごとに別々に選べます．`None` は設定の既定，`[]` は選択なしです．followerの状態は常に渡します．

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

- 空の選択は `--sensors "" --observe ""` です．launcherには，起動するsensorと方策の観測のチェック欄が別々にあり，前回の選択を保存します．
- 選ばなかったsensorのYAMLは読み込みません．起動していないsensorを観測に指定するとerrorです．
- 左右のDIGITを含め，optionで追加されるsensorも個別に選べます．選択はoptionを適用したあとに決まります．
- 任意のsensorは `config.yaml` で `{file: nodes/audio.yaml, default: false}` と宣言します．文字列のpathは既定で有効です．
- `observe` に含めないsensorも，起動すれば記録します．
- `RobotConfig` を渡すときは，`load_config(..., sensors=[...], observe=[...])` で選択を確定してください．
- 書き方の規則は [sensor選択](../../reference/configuration/sensors.md#sensor-selection) にあります．
