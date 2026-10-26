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

Rakuda2への接続は [機体ページ](../robots/rakuda2.md) を参照してください．
