#!/bin/sh
set -eu

script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_directory=$(dirname -- "$script_directory")
source_file="$project_directory/macos/PagePulse Launcher.applescript"
output_app="$project_directory/diemRenLuyen Launcher.app"

/usr/bin/osacompile -o "$output_app" "$source_file"
echo "Created: $output_app"
