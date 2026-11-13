# 音声

音声はロボット共通の任意センサーです。実機マイクは未検証です。
`uv pip install 'roboloom[audio]'` で sounddevice と librosa を追加します。
PortAudio の利用可能な入力デバイス名を指定してください。

```yaml
# config.yaml
sensors:
  audio: {file: nodes/audio.yaml, default: false}
```

```yaml
# nodes/audio.yaml
type: mel_mono
device: YOUR_MICROPHONE
channels: 1
sample_rate: 44100
window_seconds: 1.0
n_mels: 64
n_fft: 2048
hop_length: 690
fmax: 15000
```

recorder の `max_age_ms` に `audio: 1500` などの許容遅延を追加します。
`mel_mono` は直近1秒のモノラル波形を、低周波から高周波順の
`float32[64,64]` の対数メルパワーにします。center=True、power=2、
power_to_db(ref=1.0)、librosa の既定の Hann 窓・Slaney mel・top_db=80 を使います。
着色・上下反転はしません。既存の `pcm_mono` は
`int16[int(sample_rate/dataset_fps)]` を維持します。
保存キーはどちらも `observation.audio.<name>` です。

取得は InputStream と固定長バッファで継続します。時刻は窓の終端です。
初期窓が揃うまで、または新しい音声がない間は新しい有効サンプルを出しません。
記録の欠測は既存の valid フィールドで判定してください。
mock は実機用依存を読み込まず固定配列を返します。

独自 policy は数値配列として利用できます。LeRobot 標準モデルの音声エンコーダ、
PCM とメルの同時出力、ステレオは対象外です。

追記時にはキー・dtype・shape・名前と順序・FPS・robot_type を検査します。
音声処理設定は `meta/roboloom.json` でも比較します。不一致や音声メタデータが
ない旧データには追記せず、手動で repo_id と output を変更してください。
保存先の自動生成や構成 ID は追加しません。既存の options の dataset 接尾辞は維持します。
