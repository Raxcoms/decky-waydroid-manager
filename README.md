# Waydroid Manager

Set up Android from Decky and launch Android apps from your Steam library. Waydroid Manager installs the GAPPS image, manages Android packages, and creates Steam shortcuts with matching artwork.

## Get started

1. Download the `waydroid-manager-<version>.zip` asset from the [latest release](https://github.com/Raxcoms/decky-waydroid-manager/releases/latest).
2. Install the ZIP in Decky and open **Waydroid Manager** in Game Mode.
3. Choose **Install Waydroid**, then **Add Waydroid to Steam**.

For setup requirements, Android packages, or help with launch settings, see the [installation guide](docs/installation.md) and [user guide](docs/features.md).

## What you can do

- Enable a second Android screen for individual app shortcuts or the Waydroid shortcut on compatible hosts.
- Link a companion app to open on the second screen while focus stays on the primary app.
- Change Steam's frame limit live, including arbitrary whole-number caps. Each screen respects its own refresh-rate ceiling.
- Access **Host > Home** and mounted external drives through Android's file picker, with read/write access to their contents.
- Generate Steam artwork from the app's actual launcher icon and scale Android's interface with the launch resolution.

Second-screen preparation runs locally with tools included in the plugin. It needs no compiler installation or dependency downloads on ArmadaOS. Display changes and shared mounts apply only to plugin launches; installed Waydroid images remain unchanged.

## Compatibility

The current native display profile supports Android 13 / VNDK 33 / ARM64. The plugin checks the installed interfaces before using it; Android version alone does not establish compatibility. Second-screen actions appear only when the host exposes a secondary Wayland output.

Multiple independent shortcuts share one Android desktop and Steam window identity. Independent presentation ownership is not supported yet. See [second-screen support](docs/dual-screen-investigation.md) and [frame limits](docs/features.md#frame-limits) for details and fallback behavior.

## For contributors

See the [architecture overview](docs/architecture.md) for the responsibilities of Decky, Steam, Waydroid, and the bundled helpers.

Use Node 22.6 or newer with type stripping available, the pnpm version in `package.json`, and Python 3.10 or newer. CI uses Node 24. The Android helper build requires JDK 17, Android SDK Build Tools 35.0.0, and the Android 35 platform. Set `JAVA_HOME` and `ANDROID_HOME` before building.

```sh
pnpm install
pnpm run check
pnpm run build
python3 scripts/build_android.py
python3 -m unittest discover -s tests -v
node --experimental-strip-types --test tests/*.test.mts
```

Run runtime tests on Linux. These commands check the frontend and Android helpers; a complete package also needs the native libraries and private runtime tools described in the [native build guide](android/native/README.md).

[Automated CI builds](https://github.com/Raxcoms/decky-waydroid-manager/actions/workflows/build.yml) publish one installable plugin artifact, `waydroid-manager-<version>-ci.zip`. The installed version includes its commit SHA, such as `1.1.0+abcdef0`. Native libraries and runtime tools are internal cached build outputs, not separate downloads.

## Publish a release

1. Update the major.minor.patch version in `package.json` and add `docs/releases/<version>.md` with user-facing release notes.
2. Merge the changes into `main` and check CI.
3. Run **Publish Waydroid Manager release** on `main` with that version.

The workflow uses the same cached native, Android helper, frontend and package checks as regular CI. It publishes `waydroid-manager-<version>.zip` under `v<version>`, with no commit suffix in the installed version. See the [release notes](docs/releases/1.1.0.md).

## License

[Creative Commons Attribution 4.0 International](LICENSE) (CC BY 4.0).

CI-built Android display libraries retain their upstream licenses. Packaged native
builds and private host tools include their checksums and third-party notices.
See the [native build guide](android/native/README.md). Image-specific resource
overlays are built locally from the installed image; compiled outputs stay outside Git.
