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

The current shipped profile is Android 13 / VNDK 33 / ARM64. Runtime validation
also checks the installed Binder ABI and required exports. A different SoC does
not by itself require a new profile, but the Android version alone does not prove
that an image is compatible.

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

## Package the complete plugin

Use the regular GitHub build for an installable plugin ZIP. It builds the
frontend and Android helpers, restores or builds the native profile, bundles
private resource tools, and validates the final package. The official release
workflow reuses this process; `native.yml` is not required.

For a local complete build, follow the frontend and Android helper steps in the
[repository guide](../../README.md#for-contributors), then build the native
profile as above. On an Ubuntu ARM64 build runner with `aapt`, `openssl` and a C
compiler installed, bundle the matching host tools:

```sh
python3 scripts/bundle_runtime_tools.py out/display-tools
python3 scripts/package.py out/package --native out/display-native --runtime-tools out/display-tools
python3 scripts/check_package.py out/package/waydroid-manager
```

Run these commands from the repository root. The host tools must match the
target device architecture; bundling x86 tools on an x86 workstation does not
produce an ARM64 runtime package. These requirements apply to build runners,
not the ArmadaOS device receiving the plugin.

## Cache behavior

`scripts/native_cache.py` derives keys from the supported profiles, native
sources, patches and build recipes. Private tool keys include their runner
configuration and owned build inputs. Frontend or documentation changes do not
invalidate unchanged native outputs.

The package job restores these internal caches and checks the included manifests
and hashes. Only the complete plugin is uploaded as a downloadable CI artifact;
release builds publish a versioned Decky ZIP. No third-party checkout or compiled
dependency belongs in the source repository.

## Measured footprint

The Android 13 ARM64 prototype used about 242 MB of dependency sources, 61 MB of
native build output and 7 MB for host tools. Its standalone NDK occupied 1.7 GB.
The two stripped native libraries totalled about 1.4 MB. These are development
measurements; CI artifacts report their actual contents.

The device does not need this native build environment or its downloads. It only
compiles the small image-specific resource overlays, using the compiler and
signer already packaged privately with the plugin.
