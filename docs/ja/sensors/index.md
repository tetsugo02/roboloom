# Sensors

センサーは，カメラや触覚などの観測を取得するノードです．recorderが記録の行にそろえ，方策には `observe` で選んだものを渡します．画像はHWC・3チャンネルRGBで扱います．センサーの `fps` は取得周期，設定の `dataset_fps` は記録周期です．

| センサー | `type` | 出力 | 状態 |
| --- | --- | --- | --- |
| [RealSense](realsense.md) | `realsense_rgb` | RGBカメラ画像 | <span class="status status--verified">実機検証済み</span> |
| [DIGIT](digit.md) | `digit` | 触覚RGB画像 | <span class="status status--verified">実機検証済み</span> |
| [音声](audio.md) | `mel_mono`，`pcm_mono` | メルスペクトログラム，PCM | <span class="status status--dev">開発中</span> |
| [Pikaの手首カメラ](pika-cameras.md) | `v4l2_rgb`，`realsense_rgb` | 魚眼とD405のRGB画像 | <span class="status status--dev">開発中</span> |
| [Webカメラ](webcam.md) | `opencv_rgb` | RGBカメラ画像 | <span class="status status--dev">開発中</span> |

## 機体ごとの対応 { #by-robot }

| 機体 | RealSense | DIGIT | 音声 | Pikaの手首カメラ | Webカメラ |
| --- | --- | --- | --- | --- | --- |
| [Rakuda2](../robots/rakuda2/sensors.md) | <span class="status status--verified">実機検証済み</span> | <span class="status status--verified">実機検証済み</span> | <span class="status status--dev">開発中</span> | — | <span class="status status--dev">開発中</span> |
| [PiPER＋Pika Gripper](../robots/piper/index.md) | <span class="status status--dev">開発中</span> | — | <span class="status status--dev">開発中</span> | <span class="status status--dev">開発中</span> | <span class="status status--dev">開発中</span> |
| [Pika Senseを手に持つ](../tutorials/pika-handheld.md) | — | — | — | <span class="status status--dev">開発中</span> | — |

音声とWebカメラは，どの機体の設定にも足せる種類です．方策の種類まで含めた表は [対応表](../get-started/support-matrix.md) にあります．

## Recorderの設定 { #recorder }

どのセンサーも，`nodes/recorder.yaml` の `max_age_ms` にノード名をキーとした項目が必要です．データセットの行に使えるサンプルの古さの上限（ms）で，それより古いものは欠測として記録します（`valid` は0．値は直前の有効なサンプルを繰り返し，まだ一度も届いていないときだけ0）．inputとfollowerにも必要です．項目が無いと，設定の読み込みが `max_age_ms.<name>: expected positive finite number`（例：`max_age_ms.digit_left: expected positive finite number`）で失敗します．

```yaml
max_age_ms:
  leader: 200
  follower: 200
  camera: 200
  digit_left: 200
  digit_right: 200
```

Rakuda2のテンプレートには `camera`，`digit_left`，`digit_right` の項目があります．センサーを追加したときやノード名を変えたときは，この項目も追加・変更します．構成にないノードの項目は無視されるので，テンプレートはどのオプションの項目も持っています（`digit` オプションを使わないときの `digit_left` など）．名前を打ち間違えた項目も同じく無視され，読み込みは正しい名前のノードの項目がないと報告します．

`storage: video` の画像の codec（AV1 か H.264）は，同じ `nodes/recorder.yaml` の `video_codec` で選びます（[Video codec](../reference/configuration/recorder.md#video-codec)）．
