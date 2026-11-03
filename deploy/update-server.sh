#!/usr/bin/env bash
# Update an existing production installation using a verified release bundle.
# Usage: sudo bash deploy/update-server.sh /path/to/unpacked/sugar-watch-release
set -euo pipefail
umask 027
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo "Run with sudo and one unpacked release directory." >&2; exit 2; }
[[ -f /etc/sugar-watch/server-deploy.conf && -f /etc/sugar-watch/app.env ]] || {
    echo "Required production deployment configuration is missing." >&2; exit 2;
}
config=/etc/sugar-watch/server-deploy.conf
[[ $(stat -c %u "$config") == 0 && $(stat -c %a "$config") == 600 ]] || {
    echo "Deployment configuration must be root-owned with mode 0600." >&2; exit 2;
}
# This root-owned file is shell configuration created by the server administrator.
source "$config"
: "${MYSQL_BACKUP_CONFIG:?}" "${BACKUP_DIRECTORY:?}" "${GPG_RECIPIENT:?}" "${SMOKE_HOST:?}"
[[ "$SMOKE_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || exit 2
source_dir=$(realpath -- "$1")
[[ -f "$source_dir/RELEASE.json" ]] || { echo "Not a packaged release." >&2; exit 2; }
id sugarwatch >/dev/null
command -v flock >/dev/null
exec 9>/run/lock/sugar-watch-update.lock
flock -n 9 || { echo "Another update is in progress." >&2; exit 2; }
# Verify the exact package contents before stopping anything or running its code.
python3 - "$source_dir" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / 'RELEASE.json').read_text())['files']
actual = set()
for path in root.rglob('*'):
    if path.is_symlink():
        raise SystemExit('Release contains a symbolic link.')
    if path.is_file() and path.name != 'RELEASE.json':
        actual.add(path.relative_to(root).as_posix())
if actual != set(manifest):
    raise SystemExit('Release contents differ from the manifest.')
for name, digest in manifest.items():
    path = pathlib.PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        raise SystemExit('Invalid release path.')
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
        raise SystemExit('Release checksum failed.')
PY
base=/opt/sugar-watch
[[ -L "$base/current" ]] || { echo "Initial server installation is required before using updates." >&2; exit 2; }
release="$base/releases/$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0755 "$release"
cp -a "$source_dir/." "$release/"
chown -R root:root "$release"
chmod -R u+rwX,go+rX,go-w "$release"
umask 022
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --disable-pip-version-check -r "$release/requirements.txt"
umask 027
(cd "$release" && runuser -u sugarwatch -- env PYTHONDONTWRITEBYTECODE=1 "$release/.venv/bin/python" scripts/check_release.py)
timer_active=false
systemctl is-active --quiet sugar-watch-libre-sync.timer && timer_active=true
sync_stopped=false
app_stopped=false
switched=false
recover() {
    result=$?
    if [[ $result -ne 0 ]]; then
        if $switched; then
            systemctl stop sugar-watch.service || true
            echo "Update failed after release switch. App and Libre timer remain stopped. Inspect migrations before rollback; use the pre-update backup if needed." >&2
        else
            if $app_stopped; then systemctl start sugar-watch.service || true; fi
            if $sync_stopped && $timer_active; then systemctl start sugar-watch-libre-sync.timer || true; fi
        fi
    fi
}
trap recover EXIT
if systemctl cat sugar-watch-libre-sync.timer >/dev/null 2>&1; then
    systemctl stop sugar-watch-libre-sync.timer
    sync_stopped=true
    systemctl stop sugar-watch-libre-sync.service || true
fi
systemctl stop sugar-watch.service
app_stopped=true
bash "$release/deploy/backup-mysql.sh" "$MYSQL_BACKUP_CONFIG" "$BACKUP_DIRECTORY" "$GPG_RECIPIENT"
readlink -f "$base/current" > "$release/PREVIOUS_RELEASE"
install -m 0644 "$release/deploy/sugar-watch.service" /etc/systemd/system/sugar-watch.service
install -m 0644 "$release/deploy/sugar-watch-libre-sync.service" /etc/systemd/system/sugar-watch-libre-sync.service
install -m 0644 "$release/deploy/sugar-watch-libre-sync.timer" /etc/systemd/system/sugar-watch-libre-sync.timer
systemctl daemon-reload
ln -s "$release" "$base/.next-$$"
mv -Tf "$base/.next-$$" "$base/current"
switched=true
systemctl start sugar-watch.service
healthy=false
for attempt in {1..30}; do
    code=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 -H "Host: $SMOKE_HOST" http://127.0.0.1:8000/ || true)
    if systemctl is-active --quiet sugar-watch.service && [[ "$code" =~ ^(200|302|303|307)$ ]]; then healthy=true; break; fi
    sleep 1
done
$healthy || { echo "Application startup check failed." >&2; exit 1; }
if $timer_active; then systemctl start sugar-watch-libre-sync.timer; fi
echo "Updated successfully: $release"
echo "Existing Libre timer state preserved. Verify external HTTPS, sign-in, and sync on the production host."
