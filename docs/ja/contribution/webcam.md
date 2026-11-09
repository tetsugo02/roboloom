# Webカメラ（開発中・実機未検証）

!!! warning "開発中"
    USB／内蔵のWebカメラをOpenCVで取得するための，開発中の記録です．Linux・macOS・Windows向けのドライバーを実装していますが，偽のOpenCVを使った試験と模擬だけで確かめており，どのOSでも実機では確かめていません．Windowsでの `Session`・録画全体は対象外です（今の `Session` はUnixのFIFOとプロセス制御を使います）．

## インストール

OpenCV（`opencv-python-headless`）は共通依存に含まれ，カメラ用のextraは不要です．録画には `record`，ロボットには機体用のextraを追加します（[インストール](../quick-start/installation.md)）．

## 設定

```yaml
# nodes/camera.yaml
type: opencv_rgb
device: 0
backend: auto
width: 640
height: 480
fps: 30
storage: video
```

| キー | 動作 |
| --- | --- |
| `device` | 必須．非負整数．Linuxでは `/dev/videoN`，`/dev/v4l/by-id/...`，`/dev/v4l/by-path/...` も使えます．動画ファイルとURLは使えません |
| `backend` | 既定は `auto` で，Linuxは `v4l2`，macOSは `avfoundation`，Windowsは `msmf` を選びます．Windowsでは `dshow` も指定できます．別のバックエンドへ自動では切り替えません |
| `width`，`height` | 必須の正の整数．実際のフレームの大きさが違えば読み取り時に拒否します．自動では縮小・拡大しません |
| `fps` | 必須．取得周期の要求です．設定できない，報告されない，報告値が要求と0.5 fpsより大きく違う場合は，警告して続けます |
| `format` | 任意．`MJPG` または `YUYV`．省略するとバックエンドの既定です．設定できない，確かめられない，違う形式が報告された場合は，報告された形式を添えて警告します |
| `storage` | `video`（既定）または `image`．[保存形式](../reference/configuration.md#image-storage) を参照してください |

`backend` とOSの組み合わせ（例：Linuxで `dshow`）と，Linux以外での `/dev/` パスは，設定の読み込み（`validate`，模擬）では拒否せず，実機のカメラを開くときに `ValueError` で止めます．模擬の設定を別のOSでも確かめられるようにするためです．複数のOSで同じ設定を使うときは `backend: auto` にします．

Linuxでは安定したデバイスパスを勧めます．パスと対応するモードは `ls -l /dev/v4l/by-path/` と `v4l2-ctl -d <device> --list-formats-ext`（v4l-utilsが必要）で調べます．macOSとWindowsでは，カメラの仕様やOSのカメラアプリで解像度を調べ，番号を明示して確かめます．番号は接続の順番などで変わることがあります．Linuxではデバイスのアクセス権，macOSでは起動するアプリのカメラの許可，Windowsではデスクトップアプリのカメラの許可を確認してください．

同じ番号を2つのセンサーに指定すると拒否します．Linuxでは番号とパス・シンボリックリンクの重複も見つけます．macOSとWindowsでは，バックエンドが違う指定どうしで同じ物理カメラかどうかまでは判別できません．

`config.yaml` の `sensors.camera: nodes/camera.yaml` に登録し，Recorderの `max_age_ms.camera` を設定します（[Sensors](../sensors/index.md)）．Rakuda2では既存の `nodes/camera.yaml` を上の設定に差し替え，同じノード名を使えます．ただし，この組み合わせは実機で確かめていません．テンプレートの既定はRealSenseのままです．カメラを変えると方策の入力画像が変わるので，別のデータセットの出力を勧めます．大きさや保存形式が変わる場合は別の出力が必須です．

## Python API

```python
import time

from roboloom.sensors.vision.opencv import OpenCVRGB

camera = OpenCVRGB(
    "camera",
    {
        "device": 0,
        "width": 640,
        "height": 480,
        "fps": 30,
    },
)
reader = camera.open(mock=False, dataset_fps=10)
try:
    for _ in range(30):
        sample = reader.read()
        if sample is not None:
            print(sample.value.shape, sample.capture_ns)
        time.sleep(1 / 30)
finally:
    reader.close()
```

この例はカメラだけを開きます．`mock=True` はOpenCVをimportせず，実機にも接続せずに黒い画像を返します．`reader.read` を `InProcessSession` の `sensors` に渡す場合も，終了時の `reader.close()` は呼び出し側で行います．

## 出力と制約

画像はHWC・uint8・RGBで，featureは `observation.images.<名前>` です．時刻は受信後の単調時計で，露光の時刻ではありません．カメラ間の同期は保証しません．`fps` は取得の要求，`dataset_fps` は記録周期です．

読み取りは同期式です．フレームが取れなければ `None` を返し，1秒を超えて取れないと，次に読み取りが戻ったときに `ConnectionError` になります．OpenCVの `read()` が戻らない場合に強制的に打ち切る仕組みはありません．バッファを1枚に要求しますが，バックエンドが無視することがあるため，いつも最新の画像である保証はありません．切断時に自動では再接続しません．

既存の `v4l2_rgb` は，Linuxでの形式・大きさ・fpsの厳格な検査を保ちます．RealSenseの深度や校正情報，露光の設定，GUIでのプレビューは追加しません．
