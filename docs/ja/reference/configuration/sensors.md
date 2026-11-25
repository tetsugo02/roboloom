# sensor（sensors）

`sensors:` のnode YAMLのkeyです．sensorは記録するだけの機器で，`observe` に入れると方策にも渡ります．機器ごとの準備と制約は [Sensors](../../sensors/index.md) の各ページを参照してください．recorderの `max_age_ms` に各sensorの項目が必要です（[recorder](recorder.md#recorder)）．

## 共通のkey { #common }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `type` | 文字列 | 必須 | — | `realsense_rgb`，`digit`，`v4l2_rgb`，`opencv_rgb`，`pcm_mono`，`mel_mono` か `module:Class` |
| `fps` | 数値 | 画像sensorでは必須 | Hz | 読む周期（[制御周期](followers.md#control-rate) の規則に従う）．音声のsensorは持たない（書くと拒否） |

## 画像sensorの共通のkey { #image }

`realsense_rgb`，`digit`，`v4l2_rgb`，`opencv_rgb` が読むkeyです．画像はHWCのuint8 RGBで，`observation.images.<sensor>` に記録します．形が設定と違うframeは拒否します．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `fps` | 数値 | 必須 | Hz | cameraに求める周期 |
| `width` | 整数 | 必須 | px | 幅 |
| `height` | 整数 | 必須 | px | 高さ |
| `storage` | 文字列 | `video` | — | `video`（非可逆のMP4）か `image`（可逆のPNG）（[下記](#image-storage)） |

## 画像の保存形式（storage） { #image-storage }

画像sensorのnode YAMLに `storage: video | image` を指定します（RealSense，DIGIT，Pika手首cameraを含むV4L2）．既定は `video` で，従来の非可逆MP4です．`image` は可逆PNG frameをParquetに埋め込みます．DIGITと背景の微小な画素差を使う場合に推奨します．同じdataset内で混在できます．不正な値は `validate` を含む設定読み込み時に拒否します．

PNGは一般に容量とPNG圧縮・書き込み負荷が増えます．実際の容量と速度は画像内容と機器に依存します．非圧縮RGBの参考値は320×240×3，dataset fps 30でsensorあたり6.9 MB/s（640×480は27.6 MB/s）です．PNGの実測値ではありません．LeRobotの `image` のPNG圧縮levelは6です．保存形式の変更はfeature dtypeの変更になるため，別のdataset `output` を指定してください．以前のschemaへの追記は拒否します．

live観測は引き続きHWC uint8 RGBです．LeRobotの読み出しは両形式とも既定でCHW float32，範囲 [0, 1] になり，checkpointの入力型は `VISUAL` のままです．保存形式は <span class="status status--mock">模擬のみ</span> で，mock・合成frameのみで試験し，実機では未検証です．`storage: video` のcodecは [recorder の `video_codec`](recorder.md#video-codec) で選びます．

## realsense_rgb { #realsense }

Intel RealSenseのcolor画像です（[RealSense](../../sensors/realsense.md)）．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `serial` | 文字列 | 必須 | — | serial番号（`rs-enumerate-devices`） |

## digit { #digit }

DIGITの触覚画像です（[DIGIT](../../sensors/digit.md)）．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `serial` | 文字列 | 必須 | — | serial番号 |
| `resolution` | 文字列 | `QVGA` | — | `QVGA` か `VGA`．`height` と `width` はこれに合わせる（`QVGA`：`height: 320`，`width: 240`．`VGA`：`height: 640`，`width: 480`） |
| `name` | 文字列 | `serial` の値 | — | `digit_interface` に渡す名前 |
| `seam_check` | 真偽値 | `true` | — | frameごとのrow seam検査．seamのあるframeを破棄し，rollしたstreamを開き直す（[DIGIT](../../sensors/digit.md#row-seam)）．`false` は従来の動作 <span class="status status--mock">模擬のみ</span> |
| `recover_after` | 1以上の整数 | `3` | — | streamを閉じて開き直すまでの連続seam数 <span class="status status--mock">模擬のみ</span> |
| `warmup_frames` | 0以上の整数 | `10` | — | openのあとに破棄するframe数（開き直しでも同じ） <span class="status status--mock">模擬のみ</span> |

`fps` は，その解像度で機器が対応する値だけを受け付けます（開くときに確かめます）．

## v4l2_rgb <span class="status status--dev">開発中</span> { #v4l2 }

Video4Linux2のUSB（UVC）cameraです．Pika SenseとPika Gripperの魚眼cameraに使います（[Pikaのcamera](../../sensors/pika-cameras.md)）．開くときに形式・大きさ・周期を設定し，そのとおりに出ないcameraは拒否します．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `device` | 文字列 | 必須 | — | `/dev/v4l/by-path/...` か `/dev/v4l/by-id/...`（`/dev/video<n>` は起動ごとに変わりうる） |
| `format` | 文字列 | `MJPG` | — | `MJPG` か `YUYV` |

## Web camera（opencv_rgb） <span class="status status--dev">開発中</span> { #webcam }

OpenCVで読むUSB cameraと内蔵cameraです．実機では確かめていません．詳細とOSごとの制約は [Web camera](../../sensors/webcam.md) を参照してください．大きさは厳密に確かめ，`fps` と `format` は要求として送ります．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `device` | 0以上の整数か `/dev/` のpath | 必須 | — | cameraの番号かpath．pathは `backend` が `auto` か `v4l2` のときだけ使える |
| `backend` | 文字列 | `auto` | — | `auto`，`v4l2`，`avfoundation`，`msmf`，`dshow` |
| `format` | 文字列 | — | — | `MJPG` か `YUYV` |

## 音声（pcm_mono，mel_mono） <span class="status status--dev">開発中</span> { #audio }

monoのmicです（[音声](../../sensors/audio.md)）．datasetの1 frameにつき1つの塊を `observation.audio.<sensor>` に記録します．`fps` は持ちません．

`pcm_mono` は，int16のPCM（`sample_rate / dataset_fps` sample）を記録します．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `device` | 文字列 | 必須 | — | 入力device |
| `channels` | 整数 | 必須 | — | `1` だけ |
| `sample_rate` | 数値 | 必須 | Hz | sampling周波数 |

`mel_mono` は，直近 `window_seconds` 秒の対数mel power（float32，`[n_mels, 1 + window samples // hop_length]`）を記録します．`pcm_mono` のkeyに加えて，次を読みます．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `sample_rate` | 数値 | `44100` | Hz | sampling周波数 |
| `window_seconds` | 数値 | `1.0` | s | 窓の長さ．窓は `n_fft` 以上 |
| `n_fft` | 整数 | `2048` | sample | FFTの長さ |
| `hop_length` | 整数 | `690` | sample | frameの間隔 |
| `n_mels` | 整数 | `64` | — | mel帯域の数 |
| `fmax` | 数値 | `15000` | Hz | 最高周波数（Nyquist周波数以下） |

## sensorの選択 { #sensor-selection }

`load_config(..., sensors=[...], observe=[...])` と `Session.launch(..., sensors=[...], observe=[...])` で，起動・記録するsensorと，方策に渡す観測を独立に指定します．`None` は設定の既定，`[]` は選択なしです．followerの状態は常に渡します．`RobotConfig` を渡す場合は `load_config` で選択を確定してください（`Session.launch` に選択の引数を足すとerrorです）．

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
- launcherにはsensor起動とpolicy観測の独立したチェック欄があり，前回の選択を保存します．
- 選ばなかったsensorのYAMLは読み込みません．起動していないsensorを観測に指定するとerrorです．
- 左右のDIGITを含め，optionで追加されるsensorも個別に選べます．
- 既定で起動しないsensorは，`config.yaml` で `{file: nodes/audio.yaml, default: false}` と宣言します．従来の文字列のpathは既定で有効です．選択はoptionを適用したあとに解決します．
- `observe` に含めないsensorも，起動すれば記録します．

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
