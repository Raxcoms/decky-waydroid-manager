#!/usr/bin/env bash
set -euo pipefail

build_dir="${1:?Usage: prepare_hwc_build.sh BUILD_DIRECTORY}"
mkdir -p "$build_dir"
cd "$build_dir"
build_dir="$PWD"
if [[ "$build_dir" == / || "$build_dir" == "$HOME" ]]; then
  echo "Select a dedicated Android build directory." >&2
  exit 1
fi

mkdir -p tools
if [[ ! -f tools/repo ]]; then
  curl --fail --location https://storage.googleapis.com/git-repo-downloads/repo -o tools/repo
fi
repo() { python3 "$build_dir/tools/repo" "$@"; }
if [[ ! -d .repo ]]; then
  repo init -u https://github.com/LineageOS/android.git -b lineage-20.0 --depth=1 --git-lfs --no-clone-bundle
fi
repo sync -c -j4 --no-tags --no-clone-bundle build/make
mkdir -p .repo/local_manifests
for fragment in 00-remotes 01-removes 02-waydroid; do
  curl --fail --location "https://raw.githubusercontent.com/waydroid/android_vendor_waydroid/lineage-20/manifest_scripts/manifests-33/$fragment.xml" \
    -o ".repo/local_manifests/$fragment.xml"
done
repo sync -c -j4 --no-tags --no-clone-bundle
repo manifest -r -o source-manifest.xml
echo "Android sources are ready in $build_dir"
