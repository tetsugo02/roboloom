# RealSense

`RealSenseRGB` は `pyrealsense2` で **カラーストリームのみ** を取得します．`hardware` extraが必要です．

```yaml
type: realsense_rgb
serial: SET_REALSENSE_SERIAL
width: 640
height: 480
fps: 30
```

`serial` を接続したカメラのシリアル番号に置き換えます．SDKの `rs-enumerate-devices` が利用可能なら番号と接続情報を確認できます．幅・高さ・fpsは，そのデバイスが対応する組み合わせにします．

RGB8の画像を取得し，`observation.images.camera` に保存します（ノード名が `camera` の場合）．USB 3以外で接続しているとフレーム落ちの警告が表示されます．深度画像・点群・カメラ校正値はこのストリームでは出力しません．

ノードには `nodes/recorder.yaml` の `max_age_ms` の項目も必要です．[Sensors](index.md) の「Recorderの設定」を参照してください．

Rakuda2への接続は [機体ページ](../robots/rakuda2.md) を参照してください．

### Image storage

画像センサーのノード YAML に `storage: video | image` を指定します（RealSense、DIGIT、Pika 手首カメラを含む V4L2）。既定は `video` で、従来の非可逆 MP4 です。`image` は可逆 PNG フレームを Parquet に埋め込みます。DIGIT と背景の微小な画素差を使う場合に推奨します。同じデータセット内で混在できます。不正な値は `validate` を含む設定読み込み時に拒否します。

PNG は一般に容量と PNG 圧縮・書き込み負荷が増えます。実際の容量と速度は画像内容と機器に依存します。非圧縮 RGB の参考値は 320×240×3、dataset fps 30 でセンサーあたり 6.9 MB/s（640×480 は 27.6 MB/s）です。PNG の実測値ではありません。LeRobot 0.6.1 の `image` の PNG 圧縮レベルは 6 です。保存形式の変更は feature dtype の変更になるため、別のデータセット `output` を指定してください。以前のスキーマへの追記は拒否します。

ライブ観測は引き続き HWC uint8 RGB です。LeRobot の読み出しは両形式とも既定で CHW float32、範囲 [0, 1] になり、チェックポイントの入力型は `VISUAL` のままです。保存形式は mock・合成フレームのみで試験し、実機では未検証です。

`video` の MP4 の codec（既定 H.264，または AV1）は recorder の [`video_codec`](../reference/configuration.md#video-codec) で選びます．

[Configuration](../reference/configuration.md#image-storage)
