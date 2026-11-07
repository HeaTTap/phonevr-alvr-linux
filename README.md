# PhoneVR + ALVR Wired 120Hz Setup for Linux and Android 16

This repository is a patched fork of PhoneVR configured for low-latency 120Hz wired USB (ADB) VR streaming on Linux (CachyOS / Arch Linux, Wayland, hybrid Intel + NVIDIA GPUs) with Android 16 devices (tested on Samsung Galaxy A57 5G / Exynos).

i made this to save your broke ahhh from buying a vr headset for linux, all you need now is a phone and laptop. also fyi the only game i tested was war thunder. My phone got kinda hot so do beware, try and lower your brightness and disable HDR if needed

## What This Fixes

1. **Samsung Exynos 120Hz Hardware HEVC Decode (`BAD_VALUE` crash fix)**
   - PhoneVR v2.0.0-beta bundles `libalvr_client_core.so` (`v20.8.0`), which hardcodes MediaCodec `operating-rate` to `INT32_MAX` (`2147483647`). Samsung's Exynos hardware HEVC decoder (`c2.exynos.hevc.decoder`) rejects `INT32_MAX` with `codec2_status_t = BAD_VALUE (2)`.
   - Patched `libalvr_client_core.so` (`0x5f4348`) to set the default `operating-rate` to `120`.

2. **Head-Tracking Rubber-Band / Snap-Back Fix (`16ms` Prediction Cap)**
   - Because PhoneVR does not perform client-side timewarp or call `alvr_report_compositor_start`, ALVR's `statistics_manager` calculates a runaway `total_pipeline_latency` of `800ms - 1150ms` even when actual encode + decode latency is `~11ms`.
   - Feeding a `+1.1s` future timestamp into `CardboardHeadTracker_getPose` caused Cardboard's EKF (`SensorFusionEkf::PredictRotation`) to overshoot head rotation while moving and snap backward when head movement stopped.
   - Patched `alvr_get_head_prediction_offset_ns` (`0x354a5c` in `libalvr_client_core.so`) to return a fixed `16,000,000 ns` (`16ms`) offset, matching MoonlightVR.

3. **Android 16 Cardboard Sensor Polling + 6Hz Velocity Low-Pass Filter**
   - PhoneVR's bundled `libGfxPluginCardboard.so` (Cardboard v1.3) relied on `ALooper_pollAll`, which is obsoleted on Android 16 (SDK 36), and never enabled Cardboard's EKF velocity low-pass filter (`velocity_filter_ == nullptr`), causing raw single-sample MEMS gyroscope noise to jitter forward pose prediction.
   - Upgraded `libGfxPluginCardboard.so` to use `ALooper_pollOnce`, added `libc++_shared.so`, patched `CardboardOpenGlEs2DistortionRenderer_create` for 0-argument ABI compatibility, and patched `CardboardHeadTracker_create` to automatically call `HeadTracker::SetLowPassFilter(6)` (6Hz cutoff, matching MoonlightVR).

4. **360Hz Tracking Loop Sync (`3x 120Hz`)**
   - Updated `inputThread()` in `libnative-lib-alvr.so` (`0x187bc`) from `180Hz` (`1e9 / 60 / 3`, which beat against `120Hz`) to `360Hz` (`2,777,777 ns = 1e9 / 120 / 3`).

5. **OpenGL ES Triple-Buffer Ghosting / Frame-Jump Fix**
   - In `Java_viritualisres_phonevr_ALVRActivity_renderNative`, whenever `alvr_get_frame()` returned `-1` on a `120Hz` VSync (for example when a game runs at `105 - 118 FPS`), PhoneVR returned early without drawing to the current EGL backbuffer. Android's `GLSurfaceView` then immediately called `eglSwapBuffers()` on an un-updated swapbuffer from 2-3 frames earlier, causing frozen ghost cursors and backward frame jumps during head turns.
   - Patched `renderNative` (`0x197d4` in `libnative-lib-alvr.so`) so that when `alvr_get_frame()` returns `-1`, PhoneVR re-draws the latest valid `CTX.streamTextures` into the current backbuffer.

6. **100-Degree Field of View and Optional Zero-Depth Monoscopic Mode**
   - Patched `CardboardLensDistortion_getFieldOfView` (`0x4d014`) from Cardboard v1's narrow `80 deg` (`+-40 deg`) default to `100 deg` (`+-50 deg`).
   - Added an optional monoscopic zero-depth mode (`--monoscopic`) that centers the eye camera and renders the same texture to both lenses to eliminate stereo convergence strain on close cockpit instruments.

7. **Linux ALVR + SteamVR Wired ADB Integration**
   - Included `linux-120hz-setup/adb` wrapper (clears Steam Runtime's `LD_LIBRARY_PATH` to avoid `libstdc++.so.6` `GLIBCXX` errors and normalizes `dumpsys activity` output for ALVR wired detection).
   - Included `linux-120hz-setup/phonevr-adb-forward.service` (systemd user watchdog that restores `tcp:9943` and `tcp:9944` ADB port forwarding and resets stale PhoneVR sockets automatically if the USB cable briefly disconnects).
   - Included `linux-120hz-setup/vr-reconnect` helper script and a pre-configured `linux-120hz-setup/alvr-session.json`.

## Repository Layout

- `releases/PhoneVR-120Hz-Monoscopic-100FOV.apk`: Pre-patched APK (`120Hz`, `100 deg` FOV, monoscopic zero-depth mode).
- `releases/PhoneVR-120Hz-Stereo-100FOV.apk`: Pre-patched APK (`120Hz`, `100 deg` FOV, standard 3D stereo mode).
- `code/mobile/android/PhoneVR/app/src/main/cpp/alvr_main.cpp`: Updated C++ source with the `16ms` prediction cap, `SetLowPassFilter(6)`, `360Hz` tracking loop, and EGL triple-buffer fix.
- `linux-120hz-setup/patch_phonevr_apk.py`: Binary patcher script for PhoneVR v2.0.0-beta ARM64 native libraries.
- `linux-120hz-setup/adb`: ADB wrapper for `~/.local/bin/adb`.
- `linux-120hz-setup/vr-reconnect`: Manual USB reconnect helper for `~/.local/bin/vr-reconnect`.
- `linux-120hz-setup/phonevr-adb-forward.service`: Systemd user unit for `~/.config/systemd/user/phonevr-adb-forward.service`.
- `linux-120hz-setup/alvr-session.json`: ALVR `v20.14.1` session configuration (`120Hz`, `1536x1536` per eye, HEVC `80 Mbps` CBR over wired TCP, foveated encoding disabled).

## Quick Install

1. Install one of the pre-patched APKs from `releases/` over ADB (either `PhoneVR-120Hz-Monoscopic-100FOV.apk` for zero eye strain on close gauges, or `PhoneVR-120Hz-Stereo-100FOV.apk` for standard 3D depth):
   ```bash
   adb install -r releases/PhoneVR-120Hz-Monoscopic-100FOV.apk
   ```
2. Install the Linux helper scripts and systemd watchdog:
   ```bash
   install -Dm755 linux-120hz-setup/adb ~/.local/bin/adb
   install -Dm755 linux-120hz-setup/vr-reconnect ~/.local/bin/vr-reconnect
   install -Dm644 linux-120hz-setup/phonevr-adb-forward.service ~/.config/systemd/user/phonevr-adb-forward.service
   install -Dm644 linux-120hz-setup/alvr-session.json ~/.config/alvr/session.json
   systemctl --user daemon-reload
   systemctl --user enable --now phonevr-adb-forward.service
   ```
3. Launch ALVR Dashboard and SteamVR on Linux, open PhoneVR on your phone, and use `vr-reconnect` anytime you want to manually reset the USB stream.

## Contributors

- **HeaTTap** ([@HeaTTap](https://github.com/HeaTTap)) - Project setup, testing, and configuration.
- **Claude** ([@claude](https://github.com/claude) / [Anthropic](https://github.com/anthropics)) - Initial diagnosis and troubleshooting on the phone/Android side.
- **Antigravity** ([@google-antigravity](https://github.com/google-antigravity) / [@gemini-cli](https://github.com/gemini-cli) / [Google DeepMind](https://github.com/google-deepmind)) - ARM64 reverse engineering, binary patching (120Hz Exynos MediaCodec fix, EKF prediction cap, 6Hz low-pass filter, 360Hz tracking sync, OpenGL ES triple-buffer ghosting fix, 100-degree FOV, monoscopic mode), and Linux ALVR + SteamVR integration.

## Credits and Acknowledgments

- **PhoneVR** ([PhoneVR-Developers/PhoneVR](https://github.com/PhoneVR-Developers/PhoneVR)) by viritualisres and all PhoneVR contributors for the original Android client and ALVR integration.
- **ALVR** ([alvr-org/ALVR](https://github.com/alvr-org/ALVR)) by the ALVR maintainers and contributors for the open-source VR streaming server and client core.
- **Google Cardboard SDK** ([googlevr/cardboard](https://github.com/googlevr/cardboard)) by Google for the head tracker, sensor fusion EKF, and lens distortion library.
- **MoonlightVR** ([florke64/MoonlightVR](https://github.com/florke64/MoonlightVR)) for the Android 16 Cardboard SDK build and reference EKF configuration (`SetLowPassFilter(6)` and `16ms` prediction window).
- **uber-apk-signer** ([patrickfav/uber-apk-signer](https://github.com/patrickfav/uber-apk-signer)) by Patrick Favre-Bulle for APK zipaligning and v2/v3 signing.

## License

Licensed under the GNU General Public License v3.0 (GPLv3), preserving the license of the upstream PhoneVR and ALVR projects. See `LICENSE` for details.
