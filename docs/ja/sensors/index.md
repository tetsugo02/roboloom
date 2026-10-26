# Sensors

| センサー | `type` | 出力 |
| --- | --- | --- |
| [RealSense](realsense.md) | `realsense_rgb` | RGBカメラ画像 |
| [DIGIT](digit.md) | `digit` | 触覚RGB画像 |

対応する組み合わせは [Rakuda2](../robots/rakuda2.md) に記載しています．画像はHWC・3チャンネルRGBで扱います．センサーの `fps` は取得周期，実験の `dataset_fps` は記録周期です．
