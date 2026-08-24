#!/bin/zsh

set -euo pipefail

script_dir=${0:A:h}
project_root=${script_dir:h}
raster_dir="$script_dir/raster"
exports_dir="$script_dir/exports"
app_icon_dir="$project_root/Review_Today/Assets.xcassets/AppIcon.appiconset"
packager="$script_dir/package_raster_assets.swift"
icon_master="$raster_dir/app-icon-master-v8.png"

mkdir -p "$exports_dir"

swift "$packager" resize "$raster_dir/mascot-master-v8.png" "$exports_dir/mascot-1024.png" 1024
swift "$packager" icon "$icon_master" "$exports_dir/app-icon-1024.png" 1024
swift "$packager" resize "$raster_dir/mark-master-v8.png" "$exports_dir/mark-512.png" 512

if [[ -f "$raster_dir/mascot-cutout-v8.png" && -f "$raster_dir/mark-cutout-v8.png" ]]; then
  swift "$packager" resize "$raster_dir/mascot-cutout-v8.png" "$exports_dir/mascot-cutout-1024.png" 1024
  swift "$packager" resize "$raster_dir/mark-cutout-v8.png" "$exports_dir/mark-cutout-512.png" 512
  swift "$packager" alpha-board \
    "$raster_dir/mascot-cutout-v8.png" \
    "$raster_dir/mark-cutout-v8.png" \
    "$exports_dir/transparent-assets-acceptance-board.png"
fi

for size in 16 32 64 128 256 512 1024; do
  swift "$packager" icon "$icon_master" "$app_icon_dir/icon_${size}.png" "$size"
done

swift "$packager" board \
  "$raster_dir/mascot-master-v8.png" \
  "$raster_dir/app-icon-master-v8.png" \
  "$raster_dir/mark-master-v8.png" \
  "$exports_dir/brand-acceptance-board.png"

echo "Sampled-palette GPT Image brand assets packaged into $exports_dir and $app_icon_dir"
