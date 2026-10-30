#!/usr/bin/env bash
# Usage: backup-mysql.sh /secure/mysql-backup.cnf /secure/backup-dir GPG_RECIPIENT
# Requires mysqldump, gzip, gpg and a trusted imported recipient public key.
set -euo pipefail
umask 077
if [[ $# -ne 3 ]]; then
    echo "Usage: $0 MYSQL_OPTION_FILE BACKUP_DIRECTORY GPG_RECIPIENT" >&2
    exit 2
fi
config=$(realpath -- "$1")
out=$(realpath -- "$2")
recipient=$3
[[ -f "$config" && -d "$out" ]] || exit 2
# Refuse database credentials readable by other users.
if [[ $(stat -c %a "$config") != 600 ]]; then
    echo "MySQL option file must have mode 600." >&2
    exit 2
fi
for tool in mysqldump gzip gpg; do command -v "$tool" >/dev/null; done
file="$out/sugar-watch-$(date -u +%Y%m%dT%H%M%SZ)-$$.sql.gz.gpg"
partial="$file.partial"
trap 'rm -f -- "$partial"' EXIT
mysqldump --defaults-extra-file="$config" --single-transaction --no-tablespaces \
    --routines --triggers --events sugar_watch | gzip | \
    gpg --batch --encrypt --recipient "$recipient" --output "$partial"
# No plaintext dump is written. Rename only after every pipeline stage succeeds.
mv -- "$partial" "$file"
trap - EXIT
printf 'Encrypted backup created: %s\n' "$file"
