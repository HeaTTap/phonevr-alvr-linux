#!/usr/bin/env python3
"""
Binary patcher for PhoneVR v2.0.0-beta (ARM64) on Android 16 / Samsung Exynos 120Hz.

Applies the following fixes to the native libraries inside PhoneVR:
1. libalvr_client_core.so (0x5f4348):
   Changes hardcoded MediaCodec operating-rate default from INT32_MAX (0x7fffffff)
   to 120 (0x78) so Samsung Exynos hardware HEVC decoder (c2.exynos.hevc.decoder)
   does not fail with BAD_VALUE.
2. libalvr_client_core.so (0x354a5c, alvr_get_head_prediction_offset_ns):
   Replaces unbounded total_pipeline_latency (which runs away to >1000ms because
   PhoneVR does not report client compositor timestamps) with a fixed 16ms
   (16,000,000 ns) prediction offset matching MoonlightVR.
3. libGfxPluginCardboard.so (Android 16 ALooper_pollOnce build):
   - Patches CardboardOpenGlEs2DistortionRenderer_create (0x70bac, 0x70c98) to
     accept PhoneVR's 0-argument C call and default to kGlTexture2D (0).
   - Patches CardboardHeadTracker_create (0x4d724, 0x4d73c, 0x4d76c) to
     automatically call HeadTracker::SetLowPassFilter(6) (6 Hz velocity filter
     for forward pose prediction, matching MoonlightVR).
   - Patches CardboardLensDistortion_getFieldOfView (0x4d014) to report
     50.0 degrees per half-angle (100.0 x 100.0 degrees total FOV).
4. libnative-lib-alvr.so:
   - Updates inputThread polling interval (0x187bc, 0x187c4) from 180 Hz (60*3)
     to 360 Hz (120*3 = 2,777,777 ns) to eliminate beat-frequency stutter at 120 Hz.
   - Fixes OpenGL ES triple-buffer ghosting in renderNative (0x197d4): when
     alvr_get_frame returns -1 on a 120 Hz VSync, re-draws the latest valid
     streamTextures instead of returning an unrendered EGL backbuffer to eglSwapBuffers().
   - Optional (--monoscopic): sets 0-depth monoscopic mode (both eyes render
     streamTextures[0] with centered camera offset).
"""

import argparse
import math
import pathlib
import struct


def patch_libraries(lib_dir: pathlib.Path, fov_half_deg: float = 50.0, monoscopic: bool = False) -> None:
    alvr_core = lib_dir / "libalvr_client_core.so"
    cardboard = lib_dir / "libGfxPluginCardboard.so"
    native_alvr = lib_dir / "libnative-lib-alvr.so"

    # 1. Patch libalvr_client_core.so
    with alvr_core.open("r+b") as f:
        # MediaCodec operating-rate = 120 (mov w0, #0x78)
        f.seek(0x5F4348)
        f.write(struct.pack("<I", 0x52800F00))

        # alvr_get_head_prediction_offset_ns -> return 16,000,000 ns (0x00f42400)
        f.seek(0x354A5C)
        f.write(
            struct.pack(
                "<III",
                0x52848000,  # mov w0, #0x2400
                0x72A01E80,  # movk w0, #0xf4, lsl #16
                0xD65F03C0,  # ret
            )
        )

    # 2. Patch libGfxPluginCardboard.so
    fov_rad = math.radians(fov_half_deg)
    fov_bits = struct.unpack("<I", struct.pack("<f", fov_rad))[0]
    fov_lo = fov_bits & 0xFFFF
    fov_hi = (fov_bits >> 16) & 0xFFFF
    mov_w8_lo = 0x52800008 | (fov_lo << 5)
    movk_w8_hi = 0x72A00008 | (fov_hi << 5)

    with cardboard.open("r+b") as f:
        # CardboardOpenGlEs2DistortionRenderer_create 0-arg compatibility
        f.seek(0x70BAC)
        f.write(struct.pack("<I", 0x1400000C))  # b 0x70bdc
        f.seek(0x70C98)
        f.write(struct.pack("<I", 0x2A1F03E8))  # mov w8, wzr (kGlTexture2D = 0)

        # Auto-enable HeadTracker::SetLowPassFilter(6) inside CardboardHeadTracker_create
        f.seek(0x4D724)
        f.write(struct.pack("<I", 0xF90003FF))  # str xzr, [sp]
        f.seek(0x4D73C)
        f.write(
            struct.pack(
                "<IIII",
                0xF94003E0,  # ldr x0, [sp]
                0x528000C1,  # mov w1, #6
                0x940011A5,  # bl 0x51dd8 (HeadTracker::SetLowPassFilter)
                0x14000009,  # b 0x4d76c
            )
        )
        f.seek(0x4D76C)
        f.write(struct.pack("<I", 0xF94003E0))  # ldr x0, [sp]

        # CardboardLensDistortion_getFieldOfView -> fov_half_deg
        f.seek(0x4D014)
        f.write(
            struct.pack(
                "<IIIIII",
                0xB40000A2,  # cbz x2, +0x14
                mov_w8_lo,
                movk_w8_hi,
                0x29002048,  # stp w8, w8, [x2]
                0x29012048,  # stp w8, w8, [x2, #8]
                0xD65F03C0,  # ret
            )
        )

    # 3. Patch libnative-lib-alvr.so
    with native_alvr.open("r+b") as f:
        # inputThread 360 Hz (2,777,777 ns = 0x002a62b1)
        f.seek(0x187BC)
        f.write(struct.pack("<I", 0x528C5636))  # mov w22, #0x62b1
        f.seek(0x187C4)
        f.write(struct.pack("<I", 0x72A00556))  # movk w22, #0x2a, lsl #16

        # EGL triple-buffer ghosting fix: when alvr_get_frame == -1, branch to 0x197f4
        # to redraw latest streamTextures instead of returning an unrendered backbuffer
        f.seek(0x197D4)
        f.write(struct.pack("<I", 0x54000100))  # b.eq 0x197f4

        if monoscopic:
            # Center eyeOffsets and render streamTextures[0] to both eyes
            f.seek(0x18C2C)
            f.write(struct.pack("<I", 0xB900535F))  # str wzr, [x26, #0x50]
            f.seek(0x18C68)
            f.write(struct.pack("<I", 0x52A76008))  # mov w8, #0x3b000000
            f.seek(0x18C70)
            f.write(struct.pack("<I", 0xB9005748))  # str w8, [x26, #0x54]
            f.seek(0x199EC)
            f.write(struct.pack("<I", 0xF81383A8))  # stur x8, [x29, #-0xc8]
        else:
            # Restore standard stereo eyeOffsets and right-eye texture
            f.seek(0x18C2C)
            f.write(struct.pack("<I", 0xBD005340))  # str s0, [x26, #0x50]
            f.seek(0x18C68)
            f.write(struct.pack("<I", 0xBD40E3E0))  # ldr s0, [sp, #0xe0]
            f.seek(0x18C70)
            f.write(struct.pack("<I", 0xBD005740))  # str s0, [x26, #0x54]
            f.seek(0x199EC)
            f.write(struct.pack("<I", 0xF81383A9))  # stur x9, [x29, #-0xc8]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Patch PhoneVR ARM64 native libraries.")
    parser.add_argument("lib_dir", type=pathlib.Path, help="Path to lib/arm64-v8a directory")
    parser.add_argument("--fov-half-deg", type=float, default=50.0, help="Half-FOV angle in degrees (default: 50.0 = 100 deg total)")
    parser.add_argument("--monoscopic", action="store_true", help="Enable 0-depth monoscopic rendering")
    args = parser.parse_args()
    patch_libraries(args.lib_dir, args.fov_half_deg, args.monoscopic)
    print("Successfully patched libraries in", args.lib_dir)
