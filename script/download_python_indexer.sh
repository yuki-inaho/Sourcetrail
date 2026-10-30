#!/bin/bash

# Keep this release aligned with Sourcetrail's database schema. The archive
# checksums also pin the external indexer when building with pixi.lock.
set -euo pipefail

SOURCETRAIL_PYTHON_INDEXER_VERSION="v1_db25_p6"

abort()
{
	printf 'Error: %s\n' "$*" >&2
	exit 1
}

case "$(uname -s)" in
	Darwin)
		PLATFORM="osx"
		EXPECTED_SHA256="33da5d725fc02d997250da0d7a2623436a013bfaa66361044b8aee47fb0bc90b"
		;;
	Linux)
		PLATFORM="linux"
		EXPECTED_SHA256="e911591bd0b38b8318deb5fa99fbcda399e26d71d626adfbf83d45affc4fb882"
		;;
	MINGW*|MSYS*|CYGWIN*)
		PLATFORM="windows"
		EXPECTED_SHA256="89023a36305f0cc082bbbdfb508b60f175ea150ce48ce276c3e5d57bfcd4daf3"
		;;
	*) abort "No Python indexer release is available for this operating system." ;;
esac

# Normalize paths passed by CMake on Windows, and quote paths throughout so
# checkouts with spaces work on all supported platforms.
SCRIPT_PATH="${BASH_SOURCE[0]//\\//}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_PATH="$REPOSITORY_ROOT/bin/app/data/python"
PACKAGE_NAME="SourcetrailPythonIndexer_${SOURCETRAIL_PYTHON_INDEXER_VERSION}-${PLATFORM}"
PACKAGE_URL="https://github.com/CoatiSoftware/SourcetrailPythonIndexer/releases/download/${SOURCETRAIL_PYTHON_INDEXER_VERSION}/${PACKAGE_NAME}.zip"
BINARY_NAME="SourcetrailPythonIndexer"
if [[ "$PLATFORM" == "windows" ]]; then
	BINARY_NAME="${BINARY_NAME}.exe"
fi

has_expected_version()
{
	local installed_version
	installed_version="$("$1" --version 2>/dev/null)" || return 1
	installed_version="${installed_version##* }"
	installed_version="${installed_version//$'\r'/}"
	[[ "${installed_version//./_}" == "$SOURCETRAIL_PYTHON_INDEXER_VERSION" ]]
}

if [[ -f "$TARGET_PATH/.archive-sha256" ]] &&
	[[ "$(cat "$TARGET_PATH/.archive-sha256")" == "$EXPECTED_SHA256" ]] &&
	has_expected_version "$TARGET_PATH/$BINARY_NAME"; then
	printf 'Python indexer %s is already installed.\n' "$SOURCETRAIL_PYTHON_INDEXER_VERSION"
	exit 0
fi

mkdir -p "$REPOSITORY_ROOT/build"
TEMP_PATH="$(mktemp -d "$REPOSITORY_ROOT/build/python-indexer.XXXXXXXX")"
BACKUP_PATH="$TEMP_PATH/previous-installation"

cleanup()
{
	local status=$?
	# Restore the previous installation if moving the staged release failed.
	if [[ -e "$BACKUP_PATH" || -L "$BACKUP_PATH" ]] &&
		[[ ! -e "$TARGET_PATH" && ! -L "$TARGET_PATH" ]]; then
		if ! mv -- "$BACKUP_PATH" "$TARGET_PATH"; then
			printf 'Previous installation retained at %s\n' "$BACKUP_PATH" >&2
			return 1
		fi
	fi
	rm -rf -- "$TEMP_PATH"
	return "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

ARCHIVE_PATH="$TEMP_PATH/$PACKAGE_NAME.zip"
printf 'Downloading Python indexer %s (%s).\n' "$SOURCETRAIL_PYTHON_INDEXER_VERSION" "$PLATFORM"
if command -v curl >/dev/null 2>&1; then
	curl --fail --location --retry 3 --output "$ARCHIVE_PATH" "$PACKAGE_URL"
elif command -v wget >/dev/null 2>&1; then
	wget --tries=3 --output-document="$ARCHIVE_PATH" "$PACKAGE_URL"
elif [[ "$PLATFORM" == "windows" ]] && command -v certutil.exe >/dev/null 2>&1; then
	certutil.exe -urlcache -split -f "$PACKAGE_URL" "$ARCHIVE_PATH"
else
	abort "Install curl or wget to download the Python indexer."
fi

if command -v sha256sum >/dev/null 2>&1; then
	HASH_OUTPUT="$(sha256sum "$ARCHIVE_PATH")"
elif command -v shasum >/dev/null 2>&1; then
	HASH_OUTPUT="$(shasum -a 256 "$ARCHIVE_PATH")"
else
	abort "Install sha256sum or shasum to verify the Python indexer archive."
fi
ACTUAL_SHA256="${HASH_OUTPUT%% *}"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] ||
	abort "Python indexer archive checksum mismatch; the existing installation was preserved."

if [[ "$PLATFORM" == "windows" ]]; then
	7z x -y "$ARCHIVE_PATH" "-o$TEMP_PATH"
else
	unzip -q "$ARCHIVE_PATH" -d "$TEMP_PATH"
fi

STAGED_PATH="$TEMP_PATH/$PACKAGE_NAME"
[[ -f "$STAGED_PATH/$BINARY_NAME" ]] || abort "The archive does not contain the Python indexer."
chmod +x "$STAGED_PATH/$BINARY_NAME"
has_expected_version "$STAGED_PATH/$BINARY_NAME" ||
	abort "The downloaded Python indexer cannot run or has an unexpected version."
printf '%s\n' "$EXPECTED_SHA256" > "$STAGED_PATH/.archive-sha256"

# Only replace the installation after download, extraction and execution have
# succeeded. The EXIT trap restores the backup if the final move fails.
mkdir -p "$(dirname -- "$TARGET_PATH")"
if [[ -e "$TARGET_PATH" || -L "$TARGET_PATH" ]]; then
	mv -- "$TARGET_PATH" "$BACKUP_PATH"
fi
mv -- "$STAGED_PATH" "$TARGET_PATH"
printf 'Installed Python indexer %s.\n' "$SOURCETRAIL_PYTHON_INDEXER_VERSION"
