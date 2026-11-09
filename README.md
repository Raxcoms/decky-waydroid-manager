# Waydroid Manager

Set up Android from Decky and launch Android apps from your Steam library. Waydroid Manager installs the GAPPS image, manages Android packages, and creates Steam shortcuts with matching artwork.

## Get started

1. Download the `waydroid-manager-<version>.zip` asset from the [latest release](https://github.com/Raxcoms/decky-waydroid-manager/releases/latest).
2. Install the ZIP in Decky and open **Waydroid Manager** in Game Mode.
3. Choose **Install Waydroid**, then **Add Waydroid to Steam**.

For setup requirements, Android packages, or help with launch settings, see the [installation guide](docs/installation.md) and [user guide](docs/features.md).

## Known issue

Steam's frame cap can differ from the rate Android actually renders. On the tested 120 Hz Waydroid mode, a 100 FPS cap ran at 60 FPS. See [frame cap precision](docs/features.md#known-issue-with-frame-cap-precision) for the current behavior and the Waydroid change needed to improve it.

## For contributors

See the [architecture overview](docs/architecture.md) for the responsibilities of Decky, Steam, Waydroid, and the bundled helpers.

Use Node 22 or newer, the pnpm version in `package.json`, and Python 3.10 or newer. The Android helper build requires JDK 17, Android SDK Build Tools 35.0.0, and the Android 35 platform. Set `JAVA_HOME` and `ANDROID_HOME` before building.

```sh
pnpm install
pnpm run check
pnpm run build
python3 scripts/build_android.py
python3 -m unittest discover -s tests -v
node --experimental-strip-types --test tests/*.test.mts
python3 scripts/package.py out
python3 scripts/check_package.py out/waydroid-manager
```

Run the Linux runtime and package checks on Linux. [Automated CI builds](https://github.com/Raxcoms/decky-waydroid-manager/actions/workflows/build.yml) are named `waydroid-manager-<version>-ci.zip`. The installed version includes the short commit SHA, such as `1.0.0+c670aaf`.

To publish an official release, merge the `package.json` version bump into `main`, then run **Publish Waydroid Manager release** in GitHub Actions with that version. The workflow publishes the tested Decky ZIP under a tag such as `v1.0.0`. The installed version is `1.0.0`.

## License

[Creative Commons Attribution 4.0 International](LICENSE) (CC BY 4.0).
