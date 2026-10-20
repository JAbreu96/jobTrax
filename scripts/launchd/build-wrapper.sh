#!/bin/bash
# Build the small app a scheduled job runs through, so macOS names the job in
# Login Items and permission prompts instead of "bash" or the Claude CLI's
# version number. See README.md for why.
#
#   BUNDLE_PREFIX=com.example scripts/launchd/build-wrapper.sh inbox-triage "Inbox Triage"
#
# Writes ~/Applications/Agents/Inbox Triage.app and prints the executable path
# the plist's ProgramArguments must start with.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <job-id> \"<Display Name>\"" >&2
  exit 64
fi
job_id=$1
name=$2
# Match the prefix of your plist labels.
bundle_id="${BUNDLE_PREFIX:-com.example}.$job_id"
app="$HOME/Applications/Agents/$name.app"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$app/Contents/MacOS"
clang -O2 -Wall -o "$app/Contents/MacOS/$job_id" "$here/launcher.c"

# LSUIElement keeps it out of the Dock. CFBundleName is the name macOS shows.
cat > "$app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleExecutable</key>
	<string>$job_id</string>
	<key>CFBundleIdentifier</key>
	<string>$bundle_id</string>
	<key>CFBundleName</key>
	<string>$name</string>
	<key>CFBundleDisplayName</key>
	<string>$name</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSUIElement</key>
	<true/>
</dict>
</plist>
EOF

# The ad-hoc signature binds the Info.plist to the binary. Its identity is a
# hash, so a rebuild that changes the binary makes macOS ask permission again.
codesign -s - --force --identifier "$bundle_id" "$app"
echo "$app/Contents/MacOS/$job_id"
