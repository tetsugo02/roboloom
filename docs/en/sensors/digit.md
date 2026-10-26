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

The supported Rakuda2 configurations and how to combine DIGIT with gravity compensation are on the [robot page](../robots/rakuda2.md).
