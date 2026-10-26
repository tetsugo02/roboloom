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

For connecting it to Rakuda2, see the [robot page](../robots/rakuda2.md).
