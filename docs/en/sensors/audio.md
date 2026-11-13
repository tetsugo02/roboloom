# Audio

Audio is an optional sensor shared by robots. Physical microphones are unverified.
Install sounddevice and librosa with `uv pip install 'roboloom[audio]'`.
Specify an available PortAudio input device name.

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

Add an age allowance such as `audio: 1500` under the recorder's `max_age_ms`.
`mel_mono` transforms the latest second of mono waveform into ascending-frequency
`float32[64,64]` log mel power. It uses center=True, power=2,
power_to_db(ref=1.0), and librosa defaults: Hann window, Slaney mel, top_db=80.
No coloring or vertical flip is applied. Existing `pcm_mono` retains
`int16[int(sample_rate/dataset_fps)]`.
Both use `observation.audio.<name>`.

Capture runs continuously through InputStream and a bounded buffer. Timestamps mark
the window end. Incomplete initial windows and unchanged input produce no new valid sample.
Use the existing valid fields to identify missing recorded data.
Mock capture returns fixed arrays without importing hardware dependencies.

Custom policies can consume these numeric arrays. Standard LeRobot audio encoders,
simultaneous PCM and mel output, and stereo are outside this feature.

Appending checks feature keys, dtype, shape, names and order, FPS and robot_type.
Audio processing settings are also compared through `meta/roboloom.json`.
Mismatches and old audio data without processing metadata require manually changing
repo_id and output. No automatic destination or configuration ID is generated.
Existing options' dataset suffixes are retained.
