#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="PriceTracker"
ENTRY_FILE="$ROOT_DIR/main.py"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"
VENV_DIR="$ROOT_DIR/.build-venv"

MODE="all" # all | app | dmg | pkg | clean
APP_VERSION=""
VERSION_SUFFIX=""
APP_BASENAME="$APP_NAME"
SPEC_FILE=""
APP_BUNDLE=""

sanitize_version() {
  local raw="$1"
  local cleaned
  cleaned="$(echo "$raw" | tr -cd '[:alnum:]._-')"
  if [[ -z "$cleaned" ]]; then
    echo "[ERROR] Invalid version: $raw"
    exit 1
  fi
  echo "$cleaned"
}

init_output_names() {
  if [[ -n "$APP_VERSION" ]]; then
    VERSION_SUFFIX="-$APP_VERSION"
  fi
  APP_BASENAME="${APP_NAME}${VERSION_SUFFIX}"
  SPEC_FILE="$ROOT_DIR/${APP_BASENAME}.spec"
  APP_BUNDLE="$DIST_DIR/${APP_BASENAME}.app"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [MODE] [-v VERSION]

Modes:
  all   Build .app, .dmg, and .pkg (default)
  app   Build only .app
  dmg   Build only .dmg (requires existing .app)
  pkg   Build only .pkg (requires existing .app)
  clean Remove build artifacts

Options:
  -v, --version VERSION   Append version to artifact names.
                          Example: PriceTracker-1.0.0.app/.dmg/.pkg
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      all|app|dmg|pkg|clean)
        MODE="$1"
        shift
        ;;
      -v|--version)
        if [[ $# -lt 2 ]]; then
          echo "[ERROR] Missing value for $1"
          usage
          exit 1
        fi
        APP_VERSION="$(sanitize_version "$2")"
        shift 2
        ;;
      -h|--help|help)
        usage
        exit 0
        ;;
      *)
        echo "[ERROR] Unknown argument: $1"
        usage
        exit 1
        ;;
    esac
  done
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERROR] Missing command: $1"
    exit 1
  fi
}

install_build_deps() {
  require_cmd python3
  echo "[INFO] Preparing isolated build venv at $VENV_DIR ..."
  if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
  fi
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  echo "[INFO] Installing build dependencies into venv..."
  "$VENV_DIR/bin/pip" install -r "$ROOT_DIR/requirements.txt" pyinstaller
}

scrub_sensitive_files() {
  if [[ ! -d "$APP_BUNDLE" ]]; then
    return 0
  fi

  local removed=0
  while IFS= read -r -d '' f; do
    rm -f "$f"
    removed=1
  done < <(find "$APP_BUNDLE" -type f \( -name "settings.json" -o -name "settings.*.json" \) -print0 2>/dev/null || true)

  if [[ -f "$DIST_DIR/settings.json" ]]; then
    rm -f "$DIST_DIR/settings.json"
    removed=1
  fi

  if [[ $removed -eq 1 ]]; then
    echo "[INFO] Removed settings json from build artifacts."
  fi
}

update_bundle_version() {
  if [[ -z "$APP_VERSION" ]]; then
    return 0
  fi
  local plist_file="$APP_BUNDLE/Contents/Info.plist"
  if [[ ! -f "$plist_file" ]]; then
    return 0
  fi
  if command -v /usr/libexec/PlistBuddy >/dev/null 2>&1; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$plist_file" >/dev/null 2>&1 || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $APP_VERSION" "$plist_file" >/dev/null 2>&1 || true
  fi
}

build_app() {
  install_build_deps

  echo "[INFO] Building macOS app bundle..."
  rm -rf "$BUILD_DIR" "$SPEC_FILE" "$APP_BUNDLE" "$DIST_DIR/${APP_NAME}.app"

  "$VENV_DIR/bin/python" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --name "$APP_BASENAME" \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    --specpath "$ROOT_DIR" \
    --osx-bundle-identifier "com.local.pricetracker" \
    --exclude-module PyQt5 \
    --exclude-module PySide2 \
    --exclude-module PySide6 \
    --exclude-module PyQt6.QtWebEngineWidgets \
    --collect-submodules ccxt \
    --collect-data ccxt \
    "$ENTRY_FILE"

  if [[ ! -d "$APP_BUNDLE" ]]; then
    local fallback_bundle
    fallback_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dist/${APP_BASENAME}.app"
    if [[ -d "$fallback_bundle" ]]; then
      mkdir -p "$DIST_DIR"
      rm -rf "$APP_BUNDLE"
      mv "$fallback_bundle" "$APP_BUNDLE"
    fi
  fi

  if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "[ERROR] Build failed: app bundle not found at $APP_BUNDLE"
    exit 1
  fi

  scrub_sensitive_files
  update_bundle_version
  echo "[OK] App built: $APP_BUNDLE"
}

build_dmg() {
  require_cmd hdiutil
  if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "[ERROR] Missing app bundle: $APP_BUNDLE"
    echo "[HINT] Run: $(basename "$0") app -v <version>"
    exit 1
  fi

  local dmg_file="$DIST_DIR/${APP_BASENAME}.dmg"
  rm -f "$dmg_file"

  echo "[INFO] Building DMG..."
  hdiutil create \
    -volname "$APP_BASENAME" \
    -srcfolder "$APP_BUNDLE" \
    -ov \
    -format UDZO \
    "$dmg_file"

  echo "[OK] DMG built: $dmg_file"
}

build_pkg() {
  require_cmd pkgbuild
  if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "[ERROR] Missing app bundle: $APP_BUNDLE"
    echo "[HINT] Run: $(basename "$0") app -v <version>"
    exit 1
  fi

  local pkg_file="$DIST_DIR/${APP_BASENAME}.pkg"
  rm -f "$pkg_file"

  echo "[INFO] Building PKG..."
  pkgbuild \
    --component "$APP_BUNDLE" \
    --install-location "/Applications" \
    "$pkg_file"

  echo "[OK] PKG built: $pkg_file"
}

clean_artifacts() {
  echo "[INFO] Cleaning build artifacts..."
  rm -rf "$BUILD_DIR" "$DIST_DIR" "$VENV_DIR" "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist"
  rm -f "$ROOT_DIR/${APP_NAME}.spec"
  rm -f "$ROOT_DIR/${APP_NAME}-"*.spec 2>/dev/null || true
  echo "[OK] Clean complete"
}

parse_args "$@"
init_output_names

case "$MODE" in
  all)
    build_app
    build_dmg
    build_pkg
    ;;
  app)
    build_app
    ;;
  dmg)
    build_dmg
    ;;
  pkg)
    build_pkg
    ;;
  clean)
    clean_artifacts
    ;;
  *)
    echo "[ERROR] Unknown mode: $MODE"
    usage
    exit 1
    ;;
esac
