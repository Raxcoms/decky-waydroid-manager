# Build only the display extension

This build produces the Waydroid composer and HWC adapter without checking out or
building Android. CI fetches pinned upstream dependencies into a separate cache.
The repository contains our build recipes and patches, with no vendored sources.

## Requirements

- Linux, Python 3, CMake, Ninja, a C/C++ compiler, Bison and Flex.
- Expat, Android base, JSONCPP and OpenSSL development packages.
- The Android NDK version specified by the selected profile.

On Ubuntu:

```sh
sudo apt-get install cmake ninja-build bison flex libexpat1-dev android-libbase-dev libjsoncpp-dev libssl-dev
export ANDROID_NDK_HOME=/path/to/the/required/ndk
python3 scripts/build_native.py android/native/profiles/android-13-arm64.json out/display-native
```

The regular plugin build discovers profiles from `profiles/` and builds each one.
Build outputs and third-party dependencies stay outside Git.

## What gets built

- Our patched Waydroid composer and HWC adapter.
- The required Wayland client, keyboard, FFI and sync code.
- Interface glue generated from Waydroid's interface definitions.
- Small matching host generators used only during compilation.

Android's official VNDK snapshot supplies vendor headers and link libraries.
The device supplies those Android libraries at runtime. We do not rebuild them
or package another Android platform into the plugin.

Profiles pin upstream revisions and archive checksums. Build outputs record the
recipe digest, dependencies, notices and library checksums. A new Android API or
CPU architecture requires a matching, tested profile.

## Measured footprint

The Android 13 ARM64 prototype used about 242 MB of dependency sources, 61 MB of
native build output and 7 MB for host tools. Its standalone NDK occupied 1.7 GB.
The two stripped native libraries totalled about 1.4 MB. These are development
measurements; CI artifacts report their actual contents.

The device does not need this native build environment or its downloads. It only
compiles the small image-specific resource overlays, using the compiler and
signer already packaged privately with the plugin.
