# Pikaの手首camera

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> Pika GripperとPika Senseに付いたcameraを記録するための，開発中の記録です．魚眼cameraは偽のOpenCVを使った試験と模擬だけで確かめています．D405はcodeを変えずに `realsense_rgb` で読む見込みですが，実機では確かめていません．

## camera

Pika GripperとPika Senseには，それぞれ次の2台が付いています（AgileXのpika_sdkによる）．

| camera | 読み方 | roboloomの種類 |
| --- | --- | --- |
| 魚眼のUSB camera（UVC） | V4L2，MJPG．pika_sdkの既定は1280×720@30 | `v4l2_rgb`（新規） |
| Intel RealSense D405 | pyrealsense2．serial番号で選ぶ | `realsense_rgb`（既存．colorだけ） |

方策の学習には，腕の先にあるPika Gripperのcameraを記録します．Senseのcameraは，手持ちで集めるとき（段階4）に使う予定です．

## 魚眼camera（`v4l2_rgb`）

OpenCVは共通依存に含まれ，camera用のextraは不要です．camera自体はpysurviveを使いません．D405のRGBには，pyrealsense2が入る `hardware` も追加します（[Installation](../get-started/installation.md)）．

```yaml
# nodes/left_wrist.yaml
type: v4l2_rgb
device: /dev/v4l/by-path/pci-0000:00:14.0-usb-0:2:1.0-video-index0
format: MJPG             # 既定．YUYV も選べる
width: 640
height: 480
fps: 30
```

| key | 意味 |
| --- | --- |
| `device` | cameraのpath．`/dev/v4l/by-path/...`（差し込み口で決まる）か `/dev/v4l/by-id/...`（機種で決まる）を使います．`/dev/video<n>` の番号は起動のたびに変わることがあります |
| `format` | 画素の形式．`MJPG`（既定）か `YUYV` |
| `width`，`height`，`fps` | 記録する大きさと周期．cameraが実際に出す値と違えば，開くときに拒否します |

- 開くときに，形式・大きさ・周期を設定し，実際の値を確かめます．OpenCVは出せない値を黙って別の値に変えるので，違えば理由を示して止めます．
- buffer 1枚を要求しますが，backendによって無視されるため，常に最新画像とは限りません．
- 画像が1 sのあいだ届かなければ，cameraを失ったとしてnodeを止めます．
- 記録には `observation.images.<名前>`（`storage: video | image`，既定 `video`）として入ります．
- OpenCVは共通依存に含まれます．

cameraのpathと出せる形式は，次のcommandで調べます．`v4l2-ctl` はv4l-utilsのpackageにあります（入っていなければ管理者に頼みます）．

```bash
ls -l /dev/v4l/by-path/
v4l2-ctl -d /dev/v4l/by-path/...-video-index0 --list-formats-ext
```

1台のcameraが，`video-index0` と `video-index1` のように2つ現れることがあります．画像を出すのは，ふつう `video-index0` です．

## D405（`realsense_rgb`）

D405のcolorは，既存の `realsense_rgb` で読む見込みです．serial番号は `rs-enumerate-devices`（librealsenseの道具）で調べます．

```yaml
# nodes/left_wrist_d405.yaml
type: realsense_rgb
serial: "230322272619"   # D405のserial番号（例）
width: 640
height: 480
fps: 30
```

深度（depth）は記録しません．

## 模擬で確かめる

`.roboloom/piper-mock/` には，Pika Gripperの魚眼camera `left_wrist` と `right_wrist` が入っています．模擬では黒い画像です．

`.roboloom/piper-mock/` はroboloomのrepositoryにあり，installしたpackageには入っていません（`roboloom init` のtemplateは `rakuda2` だけです）．下のcommandは，cloneしたrepositoryのrootで実行します．自分のprojectでは，[repository](https://github.com/tetsugo02/roboloom) からこのdirectoryを自分の `.roboloom/` にコピーして使えます．`ik` extraが要ります（[Pika SenseとIKによる遠隔操作](../controllers/pose-ik.md)）．値（cameraのpathと大きさを含む）は模擬のためのものなので，実機に使い回さないでください．

```bash
uv run roboloom run piper-mock
```

## 実機で確かめること

- 魚眼cameraが出せる形式・大きさ・周期と，`video-index0` が画像のdeviceか．
- 1つのUSBの系統に，魚眼cameraとD405を何台までつなげるか（両手のGripperとSenseで最大8台）．帯域が足りなければ，大きさや周期を下げるか，別の系統につなぎます．
- D405のcolorが `rgb8` で開けるか，どの大きさと周期が使えるか．
- MJPGを展開する分だけ，画像が遅れて届くか（時刻は受け取った時に付けています）．
