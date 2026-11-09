# Web camera

USB／内蔵 Web カメラを OpenCV で取得します。Linux・macOS・Windows 向けのドライバーを実装していますが、試験は偽 OpenCV と mock のみで、実機未検証です。Windows の Session・録画全体は今回の対応範囲に含みません（現在の Session は Unix FIFO とプロセス制御を使用）。

## Installation

```bash
uv add git+https://github.com/tetsugo02/roboloom.git
```

OpenCV は共通依存に含まれ、追加の extra は不要です。録画には `record`、ロボットには機体用の extra も必要です。

## Configuration

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
| `device` | 必須。非負整数。Linux は `/dev/videoN` または `/dev/v4l/by-id/...`、`by-path/...` も利用可能。動画ファイル・URL は不可 |
| `backend` | 既定 `auto`。Linux → `v4l2`、macOS → `avfoundation`、Windows → `msmf`。Windows は `dshow` も指定可能。別バックエンドへ自動で切り替えません |
| `width`, `height` | 必須の正整数。実フレームが一致しなければ読み取り時に拒否。自動リサイズしません |
| `fps` | 必須の要求周期。未対応・報告不可・報告値が要求と 0.5 fps より大きく異なる場合は警告して利用 |
| `format` | 任意。`MJPG`／`YUYV`。省略時はバックエンドの既定。設定不可・確認不可・不一致は警告 |
| `storage` | `video`（既定）／`image`。[保存形式](../reference/configuration.md#image-storage) |

Linux は安定したデバイスパスを推奨します。`ls -l /dev/v4l/by-path/`、`v4l2-ctl -d <device> --list-formats-ext` でパスと対応モードを確認します（v4l-utils が必要）。macOS／Windows はカメラの仕様と OS のアプリで解像度を調べ、番号を明示して確認してください。番号は接続順などで変わり得ます。Linux のデバイスアクセス権、macOS の実行元アプリのカメラ許可、Windows のデスクトップアプリのカメラ許可を確認してください。

同じ番号の二重指定を拒否します。Linux は番号とパス・シンボリックリンクの重複も検出します。macOS／Windows のバックエンド間で同一物理カメラを完全に識別する保証はありません。

`config.yaml` の `sensors.camera: nodes/camera.yaml` に登録し、Recorder の `max_age_ms.camera` を設定します（[Sensors](index.md)）。Rakuda2 は既存の `nodes/camera.yaml` を上記に差し替え、同じノード名を使えます。既定テンプレートは RealSense のままです。カメラ変更時は学習時と画像内容が変わるため、別のデータセット出力を推奨します。サイズ・保存形式が変わる場合は別出力が必須です。

## Python API

```python
import time

from roboloom.sensors.vision.opencv import OpenCVRGB

camera = OpenCVRGB("camera", {
    "device": 0, "width": 640, "height": 480, "fps": 30,
})
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

この例はカメラだけを開きます。`mock=True` は OpenCV の import・実機接続なしで黒画像を返します。`reader.read` を `InProcessSession` の `sensors` に渡す場合も、終了時の `reader.close()` は呼び出し側で行います。

## Output and limitations

画像は HWC・uint8・RGB、feature は `observation.images.<名前>` です。時刻は受信後の単調時計で、露光時刻ではありません。カメラ間同期は保証しません。`fps` は取得要求、`dataset_fps` は記録周期です。

読み取りは同期式です。未取得は `None`、1秒以上未取得なら読み取り復帰時に `ConnectionError` です。ネイティブの `read()` が停止した場合の強制タイムアウトは保証しません。バッファ1枚を要求しますが、バックエンドによって無視されるため、常に最新画像である保証はありません。切断時の自動再接続は行いません。

既存の `v4l2_rgb` は Linux の厳格な形式・サイズ・fps 検査を維持します。RealSense の深度や校正情報、露光設定・GUI プレビューは追加しません。
