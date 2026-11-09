# DIGIT

`DigitSensor` uses `digit-interface` to capture tactile images. It requires the `hardware` extra. Set different serial numbers for the left and right sensors.

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

Because `digit-interface.get_frame()` returns a transposed image, the configured height and width are in this order. Do not swap them back to the usual QVGA/VGA width/height notation. Choose `fps` from the values the SDK supports for that resolution; unsupported values are rejected on connection.

Captured images are converted from BGR to RGB. When the node names are `digit_left` / `digit_right`, they are recorded in `observation.images.digit_left` / `observation.images.digit_right`.

Each DIGIT node also needs a `max_age_ms` entry in `nodes/recorder.yaml`; see "Recorder entry" in [Sensors](index.md).

The supported Rakuda2 configurations and how to combine DIGIT with gravity compensation are on the [robot page](../robots/rakuda2.md).

### Image storage

Set `storage: video | image` in each image sensor's node YAML (RealSense, DIGIT, V4L2 including Pika wrist cameras). The default is `video`: the existing lossy MP4 encoding. `image` embeds lossless PNG frames in Parquet; use it for DIGIT/background pixel differences. Formats can be mixed in one dataset. Invalid values are refused at configuration load, including `validate`.

PNG generally needs more disk space and PNG compression/write work; actual size and throughput depend on image content and hardware. As an uncompressed RGB reference, 320×240×3 at 30 dataset fps is 6.9 MB/s per sensor (640×480: 27.6 MB/s); these are not measured PNG rates. LeRobot 0.6.1 uses PNG compression level 6 for `image`. Changing storage changes the feature dtype: choose a separate dataset `output`; resume into the previous schema is refused.

Live observations remain HWC uint8 RGB, and LeRobot dataset reads return CHW float32 in [0, 1] for either format by default. Checkpoint inputs remain `VISUAL`. Storage was tested with mock/synthetic frames only, without hardware.

[Configuration](../reference/configuration.md#image-storage)
