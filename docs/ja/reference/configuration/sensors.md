# センサー（sensors）

`sensors:` のノードYAMLのキーです．センサーは記録するだけの機器で，`observe` に入れると方策にも渡ります．機器ごとの準備と制約は [Sensors](../../sensors/index.md) の各ページを参照してください．recorderの `max_age_ms` に各センサーの項目が必要です（[recorder](recorder.md#recorder)）．

## 共通のキー { #common }

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `type` | 文字列 | 必須 | — | `realsense_rgb`，`digit`，`v4l2_rgb`，`opencv_rgb`，`pcm_mono`，`mel_mono` か `module:Class` |
| `fps` | 数値 | 画像センサーでは必須 | Hz | 読む周期（[制御周期](followers.md#control-rate) の規則に従う）．音声のセンサーは持たない（書くと拒否） |

## 画像センサーの共通のキー { #image }

`realsense_rgb`，`digit`，`v4l2_rgb`，`opencv_rgb` が読むキーです．画像はHWCのuint8 RGBで，`observation.images.<センサー名>` に記録します．形が設定と違うフレームは拒否します．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `fps` | 数値 | 必須 | Hz | カメラに求める周期 |
| `width` | 整数 | 必須 | px | 幅 |
| `height` | 整数 | 必須 | px | 高さ |
| `storage` | 文字列 | `video` | — | `video`（非可逆のMP4）か `image`（可逆のPNG）（[下記](#image-storage)） |

## 画像の保存形式（storage） { #image-storage }

画像センサーのノードYAMLに `storage: video | image` を指定します（RealSense，DIGIT，Pika手首カメラを含むV4L2）．既定は `video` で，従来の非可逆MP4です．`image` は可逆PNGフレームをParquetに埋め込みます．DIGITと背景の微小な画素差を使う場合に推奨します．同じデータセット内で混在できます．不正な値は `validate` を含む設定読み込み時に拒否します．

PNGは一般に容量とPNG圧縮・書き込み負荷が増えます．実際の容量と速度は画像内容と機器に依存します．非圧縮RGBの参考値は320×240×3，dataset fps 30でセンサーあたり6.9 MB/s（640×480は27.6 MB/s）です．PNGの実測値ではありません．LeRobot 0.6.1の `image` のPNG圧縮レベルは6です．保存形式の変更はfeature dtypeの変更になるため，別のデータセット `output` を指定してください．以前のスキーマへの追記は拒否します．

ライブ観測は引き続きHWC uint8 RGBです．LeRobotの読み出しは両形式とも既定でCHW float32，範囲 [0, 1] になり，チェックポイントの入力型は `VISUAL` のままです．保存形式は <span class="status status--mock">模擬のみ</span> で，mock・合成フレームのみで試験し，実機では未検証です．`storage: video` のcodecは [recorder の `video_codec`](recorder.md#video-codec) で選びます．

## realsense_rgb { #realsense }

Intel RealSenseのカラー画像です（[RealSense](../../sensors/realsense.md)）．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `serial` | 文字列 | 必須 | — | シリアル番号（`rs-enumerate-devices`） |

## digit { #digit }

DIGITの触覚画像です（[DIGIT](../../sensors/digit.md)）．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `serial` | 文字列 | 必須 | — | シリアル番号 |
| `resolution` | 文字列 | `QVGA` | — | `QVGA` か `VGA`．`height` と `width` はこれに合わせる（`QVGA`：`height: 320`，`width: 240`．`VGA`：`height: 640`，`width: 480`） |
| `name` | 文字列 | `serial` の値 | — | `digit_interface` に渡す名前 |

`fps` は，その解像度で機器が対応する値だけを受け付けます（開くときに確かめます）．

## v4l2_rgb <span class="status status--dev">開発中</span> { #v4l2 }

Video4Linux2のUSB（UVC）カメラです．Pika SenseとPika Gripperの魚眼カメラに使います（[Pikaのカメラ](../../sensors/pika-cameras.md)）．開くときに形式・大きさ・周期を設定し，そのとおりに出ないカメラは拒否します．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `device` | 文字列 | 必須 | — | `/dev/v4l/by-path/...` か `/dev/v4l/by-id/...`（`/dev/video<n>` は起動ごとに変わりうる） |
| `format` | 文字列 | `MJPG` | — | `MJPG` か `YUYV` |

## Webカメラ（opencv_rgb） <span class="status status--dev">開発中</span> { #webcam }

OpenCVで読むUSBカメラと内蔵カメラです．実機では確かめていません．詳細とOSごとの制約は [Webカメラ](../../sensors/webcam.md) を参照してください．大きさは厳密に確かめ，`fps` と `format` は要求として送ります．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `device` | 0以上の整数か `/dev/` のパス | 必須 | — | カメラの番号かパス．パスは `backend` が `auto` か `v4l2` のときだけ使える |
| `backend` | 文字列 | `auto` | — | `auto`，`v4l2`，`avfoundation`，`msmf`，`dshow` |
| `format` | 文字列 | — | — | `MJPG` か `YUYV` |

## 音声（pcm_mono，mel_mono） <span class="status status--dev">開発中</span> { #audio }

モノラルのマイクです（[音声](../../sensors/audio.md)）．データセットの1フレームにつき1つの塊を `observation.audio.<センサー名>` に記録します．`fps` は持ちません．

`pcm_mono` は，int16のPCM（`sample_rate / dataset_fps` サンプル）を記録します．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `device` | 文字列 | 必須 | — | 入力デバイス |
| `channels` | 整数 | 必須 | — | `1` だけ |
| `sample_rate` | 数値 | 必須 | Hz | サンプリング周波数 |

`mel_mono` は，直近 `window_seconds` 秒の対数メルパワー（float32，`[n_mels, 1 + 窓のサンプル数 // hop_length]`）を記録します．`pcm_mono` のキーに加えて，次を読みます．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `sample_rate` | 数値 | `44100` | Hz | サンプリング周波数 |
| `window_seconds` | 数値 | `1.0` | s | 窓の長さ．窓は `n_fft` 以上 |
| `n_fft` | 整数 | `2048` | サンプル | FFTの長さ |
| `hop_length` | 整数 | `690` | サンプル | フレームの間隔 |
| `n_mels` | 整数 | `64` | — | メル帯域の数 |
| `fmax` | 数値 | `15000` | Hz | 最高周波数（ナイキスト周波数以下） |

## センサーの選択 { #sensor-selection }

`load_config(..., sensors=[...], observe=[...])` と `Session.launch(..., sensors=[...], observe=[...])` で，起動・記録するセンサーと，方策に渡す観測を独立に指定します．`None` は設定の既定，`[]` は選択なしです．フォロワの状態は常に渡します．`RobotConfig` を渡す場合は `load_config` で選択を確定してください（`Session.launch` に選択の引数を足すとエラーです）．

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

- CLIは `--sensors camera,audio --observe camera`，空の選択は `--sensors "" --observe ""` です．
- ランチャーにはセンサー起動とpolicy観測の独立したチェック欄があり，前回の選択を保存します．
- 選ばなかったセンサーのYAMLは読み込みません．起動していないセンサーを観測に指定するとエラーです．
- 左右のDIGITを含め，オプションで追加されるセンサーも個別に選べます．
- 既定で起動しないセンサーは，`config.yaml` で `{file: nodes/audio.yaml, default: false}` と宣言します．従来の文字列のパスは既定で有効です．選択はオプションを適用したあとに解決します．
- `observe` に含めないセンサーも，起動すれば記録します．

## 例 { #example }

```yaml
# nodes/camera.yaml
type: realsense_rgb
serial: SET_REALSENSE_SERIAL  # rs-enumerate-devices
width: 640
height: 480
fps: 30
storage: video
```
