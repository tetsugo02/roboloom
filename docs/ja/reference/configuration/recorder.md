# recorder と session

`config.yaml` の `recorder:` と `session:` が指すノードYAMLのキーです．記録・保存・再開のふるまいは [記録と保存](../../data/recording.md) に，記録する列は [データセットの列](../dataset-features.md) にあります．

## recorder { #recorder }

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `max_age_ms` | `{ノード名: 値}` | 必須 | ms | ノードごとに，行に使うサンプルの古さの上限．入力，フォロワ，センサー，`record: true` の推定器のすべてに必要．古いサンプルしかない行は欠測（`valid` が0）になる（[欠測の扱い](../../data/format.md#missing-data)） |
| `grace_ms` | 数値 | `500` | ms | 指令のないフォロワを待たずに行を確定するまでの時間 |
| `image_writer_threads` | 整数 | `4` | — | LeRobotの画像書き込みのスレッド数 |
| `streaming_encoding` | 真偽値 | `false` | — | LeRobotのストリーミングエンコードを使う |
| `queue_s` | 数値 | `0.5` | s | recorderの入力キューに溜める時間（ストリームごと）．保存中に古いものから捨てる |
| `video_codec` | 文字列 | — | — | `storage: video` の画像のcodec（[下記](#video-codec)） |
| `quality` | マッピング | `{}` | — | 品質の警告の閾値（[下記](#quality)） |

行は，全フォロワの指令がその区間を過ぎたとき，または `grace_ms` が過ぎたときに確定します．

```yaml
# nodes/recorder.yaml
max_age_ms:
  leader: 200
  follower: 200
  camera: 200
grace_ms: 500
image_writer_threads: 4
streaming_encoding: false
queue_s: 0.5
quality:
  max_missing_rate: 0.05
```

## 品質の警告（quality） { #quality }

`recorder.quality` の `max_missing_rate`，`min_action_valid_rate`，`max_interval_ms` で品質警告の閾値を指定できます．保存結果のmetricsとwarningsを確認します．`control_interval_ms` と `action_missing_rate`（指令のなかった行の割合）はフォロワごとで，警告にはフォロワの名前が出ます．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `max_missing_rate` | 数値 | `0.05` | 割合 | ストリームごとに，新しいサンプルのない行の割合がこれを超えると警告 |
| `min_action_valid_rate` | 数値 | `0.9` | 割合 | `action.valid` が1の行の割合がこれを下回ると警告 |
| `max_interval_ms` | 数値 | `100` | ms | フォロワの制御周期の最長の間隔がこれを超えると警告 |

## 動画のcodec（video_codec） { #video-codec }

`storage: video` の画像センサーの MP4 の codec は，`nodes/recorder.yaml` の `video_codec` で選びます．ロボットによらず同じです．`storage: image`（PNG），音声，関節などの保存は変わりません．

| `video_codec` | codec | LeRobot のエンコーダー（`vcodec`） |
| --- | --- | --- |
| 指定なし | 新しいデータセットは H.264．追記では保存済みの動画の設定 | `h264` |
| `av1`（別名 `libsvtav1`） | AV1 | `libsvtav1` |
| `h264` | H.264 | `h264`（FFmpeg の libx264） |

既定の H.264 は，再生できる環境が広いので選んでいます．LeRobot 自身の既定は AV1 です．容量を小さくしたいときは `video_codec: av1` にします．

```yaml
# nodes/recorder.yaml
video_codec: av1
```

起動ごとに変えるときは，`load_config`・`Session.launch` の `video_codec`，CLI の `--video-codec` を使います．`None`（CLI では省略）は YAML の指定のままです．

```python
from roboloom import Session, load_config

cfg = load_config("rakuda2", video_codec="h264")
with Session.launch("rakuda2", video_codec="h264") as session:
    ...
```

```bash
roboloom record --task "pick" --seconds 30 --video-codec h264
roboloom validate --video-codec h264   # 要約に video codec: h264
```

- 構成済みの `RobotConfig` を `Session.launch` に渡すときは，`load_config` で選びます．`Session.launch(cfg, video_codec=...)` は（`sensors`・`observe` と同じく）エラーにします．
- ランチャーの Devices の下の「Video codec (storage: video)」で `YAML / dataset`・`AV1`・`H.264` を選べます．選択は前回の選択として保存されます．
- dora のノードは，起動したプロセスと同じ選択で設定を読み直します．
- エンコードは LeRobot が行います．roboloom は `lerobot.configs.video.RGBEncoderConfig(vcodec=...)` を `LeRobotDataset.create`・`resume` に渡すだけです．CRF・GOP・preset は LeRobot の既定（CRF 30，GOP 2）のままで，設定項目はありません．
- 選んだ codec のエンコーダーがこの環境の FFmpeg（PyAV）にないときは，別の codec に切り替えず，起動時（`validate` を含む）に理由を示して止めます．何も記録しません．

**既存のデータセットへの追記**：LeRobot は新しいエピソードの動画を既存の MP4 につなげるので，1つのデータセットの動画は1つの codec にそろえます．`video_codec` を指定しなければ，保存済みの動画の codec と設定（CRF，GOP など）を引き継ぎます．指定した codec が保存済みの動画と違うときは，書き込む前に `video_codec: 'av1' (saved videos) -> 'h264' (requested)` のように差分を示して止めます．別の codec で録るときは，`repo_id` と `output` を変えて別のデータセットにします．roboloom は保存先を自動で分けたり，既存の動画を変換・上書きしたりしません．

| | AV1 | H.264（既定） |
| --- | --- | --- |
| 容量 | 一般に，同じ画質なら H.264 より小さい | 一般に AV1 より大きい |
| 速度 | LeRobot の既定（SVT-AV1 の速い preset）では，下の測定で H.264 と同程度．デコードは H.264 より重いことがある | 速い．多くの機器にハードウェアデコーダーがある |
| 再生互換性 | 新しい再生環境が必要．古い再生ソフト，一部のブラウザ・エディタの動画表示，ハードウェアデコーダーのない機器では再生できないことがある | ほとんどの再生ソフト・ブラウザで再生できる |

このマシンで，合成の 640×480・90 フレーム（30 fps）を記録したときの保存時間はどちらも約 0.9 秒，ファイルは AV1 が 238 KiB，H.264 が 209 KiB でした．1回の測定で，映像の中身と機器で変わります．同じ CRF の値でも codec が違えば画質は同じではありません．

VS Code の LeRobot Viewer で AV1 の動画（以前の既定）が黒く表示されるときは，H.264 の別のデータセットで録って比べてください．H.264 にすると表示されるかは確かめていません．codec の選択は <span class="status status--mock">模擬のみ</span> で，合成フレームの記録・LeRobot での読み込みと mock の dataflow で試験しました．実機のカメラでは確かめていません．

## session { #session }

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `type` | 文字列 | 必須 | — | `terminal` だけ（操作画面．[操作画面](../operator-screen.md)） |

```yaml
# nodes/session.yaml
type: terminal
```
