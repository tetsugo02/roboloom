# Sensors

| センサー | `type` | 出力 |
| --- | --- | --- |
| [RealSense](realsense.md) | `realsense_rgb` | RGBカメラ画像 |
| [DIGIT](digit.md) | `digit` | 触覚RGB画像 |

対応する組み合わせは [Rakuda2](../robots/rakuda2.md) に記載しています．画像はHWC・3チャンネルRGBで扱います．センサーの `fps` は取得周期，設定の `dataset_fps` は記録周期です．

## Recorderの設定

どのセンサーも，`nodes/recorder.yaml` の `max_age_ms` にノード名をキーとした項目が必要です．データセットの行に使えるサンプルの古さの上限（ms）で，それより古いものは欠測（0，`valid` は0）として記録します．inputとfollowerにも必要です．項目が無いと，設定の読み込みが `max_age_ms.<name>: expected positive finite number`（例：`max_age_ms.digit_left: expected positive finite number`）で失敗します．

```yaml
max_age_ms:
  leader: 200
  follower: 200
  camera: 200
  digit_left: 200
  digit_right: 200
```

Rakuda2のテンプレートには `camera`，`digit_left`，`digit_right` の項目があります．センサーを追加したときやノード名を変えたときは，この項目も追加・変更します．構成にないノードの項目は無視されるので，テンプレートはどのオプションの項目も持っています（`digit` オプションを使わないときの `digit_left` など）．名前を打ち間違えた項目も同じく無視され，読み込みは正しい名前のノードの項目がないと報告します．

`storage: video` の画像の codec（AV1 か H.264）は，同じ `nodes/recorder.yaml` の `video_codec` で選びます（[Video codec](../reference/configuration.md#video-codec)）．

[音声](audio.md): PCM とメル。ロボット共通、実機未検証。
