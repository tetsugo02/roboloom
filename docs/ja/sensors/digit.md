# DIGIT

`DigitSensor` は `digit-interface` を使って触覚画像を取得します．`hardware` extraが必要です．左右のセンサーには異なるシリアル番号を設定します．

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

Rakuda2の対応構成と重力補償との併用方法は [機体ページ](../robots/rakuda2.md) にあります．
