# R1 Eye capture

The HID framing and Eye-enable protocol in `control.py` are adapted from
[nudou350/Xreal-tools](https://github.com/nudou350/Xreal-tools), specifically
`GlassesFrame.kt` and `GlassesCommands.kt`, under Apache License 2.0.
The original license and upstream notices are retained in `licenses/`.

Changes: ported the protocol to Python/hidapi for Windows; selected only the
R1 USB ID; retained the known RGB enable request; added bounded process
lifecycle, Media Foundation color capture, native-resolution motion-aware
denoising, and the Board Vision FrameSource adapter. This package is independent
of the original standalone test directory and its environment.

The upstream NOTICE includes notices for its complete application. Board Vision
does not include that application's MediaPipe model or proprietary native libraries.
