# RealSense

`RealSenseRGB` uses `pyrealsense2` to capture **only the color stream**. It requires the `hardware` extra.

```yaml
type: realsense_rgb
serial: SET_REALSENSE_SERIAL
width: 640
height: 480
fps: 30
```

Replace `serial` with the serial number of the connected camera. If the SDK's `rs-enumerate-devices` is available, you can use it to check the number and connection information. Set width, height, and fps to a combination the device supports.

RGB8 images are captured and stored in `observation.images.camera` (when the node name is `camera`). A frame-drop warning is shown when connected over anything other than USB 3. This stream does not output depth images, point clouds, or camera calibration values.

The node also needs a `max_age_ms` entry in `nodes/recorder.yaml`; see "Recorder entry" in [Sensors](index.md).

For connecting it to Rakuda2, see the [robot page](../robots/rakuda2.md).

### Image storage

Set `storage: video | image` in each image sensor's node YAML (RealSense, DIGIT, V4L2 including Pika wrist cameras). The default is `video`: the existing lossy MP4 encoding. `image` embeds lossless PNG frames in Parquet; use it for DIGIT/background pixel differences. Formats can be mixed in one dataset. Invalid values are refused at configuration load, including `validate`.

PNG generally needs more disk space and PNG compression/write work; actual size and throughput depend on image content and hardware. As an uncompressed RGB reference, 320×240×3 at 30 dataset fps is 6.9 MB/s per sensor (640×480: 27.6 MB/s); these are not measured PNG rates. LeRobot 0.6.1 uses PNG compression level 6 for `image`. Changing storage changes the feature dtype: choose a separate dataset `output`; resume into the previous schema is refused.

Live observations remain HWC uint8 RGB, and LeRobot dataset reads return CHW float32 in [0, 1] for either format by default. Checkpoint inputs remain `VISUAL`. Storage was tested with mock/synthetic frames only, without hardware.

[Configuration](../reference/configuration.md#image-storage)
