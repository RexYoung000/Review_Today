#!/bin/zsh

set -euo pipefail

script_dir=${0:A:h}
project_root=${script_dir:h}
exports_dir="$script_dir/exports"
app_icon_dir="$project_root/Review_Today/Assets.xcassets/AppIcon.appiconset"
renderer="$script_dir/render_brand_assets.swift"

mkdir -p "$exports_dir"

swift "$renderer" render "$script_dir/review-today-app-icon.svg" "$exports_dir/app-icon-1024.png" 1024
swift "$renderer" render "$script_dir/review-today-app-icon-small.svg" "$exports_dir/app-icon-small-master-1024.png" 1024
swift "$renderer" render "$script_dir/review-today-mascot.svg" "$exports_dir/mascot-1024.png" 1024
swift "$renderer" render "$script_dir/review-today-mark.svg" "$exports_dir/mark-512.png" 512
swift "$renderer" render "$script_dir/review-today-menu-bar-mark.svg" "$exports_dir/menu-bar-mark-32.png" 32
swift "$renderer" render "$script_dir/review-today-menu-bar-mark.svg" "$exports_dir/menu-bar-mark-16.png" 16

swift "$renderer" render "$script_dir/review-today-app-icon-small.svg" "$app_icon_dir/icon_16.png" 16
swift "$renderer" render "$script_dir/review-today-app-icon-small.svg" "$app_icon_dir/icon_32.png" 32
swift "$renderer" render "$script_dir/review-today-app-icon-small.svg" "$app_icon_dir/icon_64.png" 64
swift "$renderer" render "$script_dir/review-today-app-icon.svg" "$app_icon_dir/icon_128.png" 128
swift "$renderer" render "$script_dir/review-today-app-icon.svg" "$app_icon_dir/icon_256.png" 256
swift "$renderer" render "$script_dir/review-today-app-icon.svg" "$app_icon_dir/icon_512.png" 512
swift "$renderer" render "$script_dir/review-today-app-icon.svg" "$app_icon_dir/icon_1024.png" 1024

swift "$renderer" board \
  "$exports_dir/app-icon-1024.png" \
  "$exports_dir/mascot-1024.png" \
  "$exports_dir/mark-512.png" \
  "$exports_dir/app-icon-small-master-1024.png" \
  "$exports_dir/brand-acceptance-board.png"

echo "Brand assets exported to $exports_dir and $app_icon_dir"
