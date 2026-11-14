#!/usr/bin/env bash
set -euo pipefail

source_dir="${1:?Usage: build_hwc.sh ANDROID_SOURCE_DIRECTORY OUTPUT_DIRECTORY}"
output="${2:?Missing output directory}"
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$output"
output="$(cd "$output" && pwd)"
cd "$source_dir"
export PATH="$PWD/.repo/repo:$PATH"
export GIT_COMMITTER_NAME=Raxcoms
export GIT_COMMITTER_EMAIL=mpaulo968@gmail.com
if [[ ! -f build/envsetup.sh ]]; then
  echo "Run prepare_hwc_build.sh first." >&2
  exit 1
fi
for entry in hardware/waydroid:external-display hardware/interfaces:adapter; do
  project="${entry%%:*}"
  patch_file="$project_dir/android/hwc/${entry#*:}.patch"
  if git -C "$project" apply --reverse --check "$patch_file" 2>/dev/null; then
    git -C "$project" apply --reverse "$patch_file"
  fi
done
set +u
source build/envsetup.sh
if [[ ! -f .waydroid-manager-upstream-patches ]]; then
  if ! python3 "$project_dir/scripts/verify_waydroid_patches.py" "$PWD"; then
    apply-waydroid-patches
    python3 "$project_dir/scripts/verify_waydroid_patches.py" "$PWD"
  fi
  touch .waydroid-manager-upstream-patches
fi
lunch lineage_waydroid_arm64-userdebug
expected=a575cfcc12ab79a122844218f2c6df5bd208cca0
if [[ "$(git -C hardware/waydroid rev-parse HEAD)" != "$expected" ]]; then
  echo "The composer source revision does not match the plugin patch." >&2
  exit 1
fi
patch="$project_dir/android/hwc/external-display.patch"
if git -C hardware/waydroid diff --quiet; then
  git -C hardware/waydroid apply --check "$patch"
  git -C hardware/waydroid apply "$patch"
elif ! git -C hardware/waydroid apply --reverse --check "$patch"; then
  echo "The composer source contains other changes. Preserve them before building." >&2
  exit 1
fi
adapter_patch="$project_dir/android/hwc/adapter.patch"
if git -C hardware/interfaces diff --quiet; then
  git -C hardware/interfaces apply --check "$adapter_patch"
  git -C hardware/interfaces apply "$adapter_patch"
elif ! git -C hardware/interfaces apply --reverse --check "$adapter_patch"; then
  echo "The composer adapter contains other changes." >&2
  exit 1
fi
if [[ -d vendor/waydroid-manager-overlay ]]; then
  diff -r "$project_dir/android/hwc/overlay" vendor/waydroid-manager-overlay
else
  cp -r "$project_dir/android/hwc/overlay" vendor/waydroid-manager-overlay
fi

jobs="${WAYDROID_MANAGER_BUILD_JOBS:-4}"
m -j"$jobs" hwcomposer.waydroid libhwc2on1adapter WaydroidManagerExternalDisplay
cp out/target/product/waydroid_arm64/vendor/lib64/hw/hwcomposer.waydroid.so "$output/"
cp out/target/product/waydroid_arm64/vendor/lib64/libhwc2on1adapter.so "$output/"
cp out/target/product/waydroid_arm64/system/product/overlay/WaydroidManagerExternalDisplay.apk "$output/"
cp "$project_dir/android/hwc/wayland_tablet.idc" "$output/"
cp source-manifest.xml "$output/source-manifest.xml"
python3 .repo/repo/repo manifest -r -o "$output/patched-source-manifest.xml"
git -C hardware/waydroid diff --binary > "$output/composer-source.patch"
sha256sum "$output/hwcomposer.waydroid.so"
