#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
VERSION=8.13
mkdir -p .gradle-dist
if [ ! -x ".gradle-dist/gradle-$VERSION/bin/gradle" ]; then
  URL="https://services.gradle.org/distributions/gradle-$VERSION-bin.zip"
  curl -fL "$URL" -o .gradle-dist/gradle.zip
  EXPECTED=$(curl -fsSL "$URL.sha256")
  if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL=$(sha256sum .gradle-dist/gradle.zip | cut -d ' ' -f1)
  else
    ACTUAL=$(shasum -a 256 .gradle-dist/gradle.zip | cut -d ' ' -f1)
  fi
  [ "$EXPECTED" = "$ACTUAL" ] || { echo 'Checksum inválido.'; exit 1; }
  unzip -q .gradle-dist/gradle.zip -d .gradle-dist
fi
".gradle-dist/gradle-$VERSION/bin/gradle" --no-daemon wrapper --gradle-version "$VERSION" --distribution-type bin
exec ".gradle-dist/gradle-$VERSION/bin/gradle" --no-daemon assembleDebug "-PAPP_URL=${1:-}"
