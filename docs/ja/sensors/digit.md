# DIGIT

`DigitSensor` は `digit-interface` を使って触覚画像を取得します．`digit` extraが必要です（[インストール](../quick-start/installation.md)）．左右のセンサーには異なるシリアル番号を設定します．

```yaml
type: digit
serial: SET_DIGIT_LEFT_SERIAL
name: left
resolution: QVGA
height: 320
width: 240
fps: 30
```

| `resolution` | `height` | `width` |
| --- | --- | --- |
| `QVGA` | 320 | 240 |
| `VGA` | 640 | 480 |

`digit-interface.get_frame()` が転置済みの画像を返すため，設定の高さ・幅はこの順です．一般的なQVGA/VGAの幅・高さの表記から逆にしないでください．`fps` はSDKの当該解像度の対応値から選び，非対応値は接続時に拒否されます．

取得画像はBGRからRGBへ変換されます．ノード名が `digit_left` / `digit_right` の場合，`observation.images.digit_left` / `observation.images.digit_right` に記録します．

DIGITのノードごとに，`nodes/recorder.yaml` の `max_age_ms` の項目も必要です．[Sensors](index.md) の「Recorderの設定」を参照してください．

Rakuda2の対応構成と重力補償との併用方法は [機体ページ](../robots/rakuda2.md) にあります．

### Image storage

画像センサーのノード YAML に `storage: video | image` を指定します（RealSense、DIGIT、Pika 手首カメラを含む V4L2）。既定は `video` で、従来の非可逆 MP4 です。`image` は可逆 PNG フレームを Parquet に埋め込みます。DIGIT と背景の微小な画素差を使う場合に推奨します。同じデータセット内で混在できます。不正な値は `validate` を含む設定読み込み時に拒否します。

PNG は一般に容量と PNG 圧縮・書き込み負荷が増えます。実際の容量と速度は画像内容と機器に依存します。非圧縮 RGB の参考値は 320×240×3、dataset fps 30 でセンサーあたり 6.9 MB/s（640×480 は 27.6 MB/s）です。PNG の実測値ではありません。LeRobot 0.6.1 の `image` の PNG 圧縮レベルは 6 です。保存形式の変更は feature dtype の変更になるため、別のデータセット `output` を指定してください。以前のスキーマへの追記は拒否します。

ライブ観測は引き続き HWC uint8 RGB です。LeRobot の読み出しは両形式とも既定で CHW float32、範囲 [0, 1] になり、チェックポイントの入力型は `VISUAL` のままです。保存形式は mock・合成フレームのみで試験し、実機では未検証です。

`video` の MP4 の codec（既定 H.264，または AV1）は recorder の [`video_codec`](../reference/configuration.md#video-codec) で選びます．

[Configuration](../reference/configuration.md#image-storage)
