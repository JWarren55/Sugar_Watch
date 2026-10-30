# Deployment

The deployment templates target Ubuntu Server with Python 3.12, MySQL, and a
local reverse proxy or tunnel providing public HTTPS.

## Configuration

Use `deploy/production.env.example` as a reference. Store completed configuration
at `/etc/sugar-watch/app.env`, owned by `root:sugarwatch` with permissions `0640`.
Never commit completed environment files or credentials.

| Setting | Purpose |
| --- | --- |
| `APP_ENV` | Set to `production`. |
| `DATABASE_URL` | MySQL URL for the application database. URL-encode password characters. |
| `SECRET_KEY` | Random session-signing secret of at least 32 characters. |
| `ALLOWED_HOSTS` | Exact application hostnames without a scheme or path. |
| `ALLOWED_EMAILS` | Comma-separated approved Google email addresses. |
| `GOOGLE_CLIENT_ID` | Production Google Web OAuth client ID. |
| `GOOGLE_CLIENT_SECRET` | Production Google OAuth client secret. |

Register `https://<hostname>/auth/google/callback` as the production Google
redirect URI. Verified email addresses must match the configured allowlist.
Restart the service after changing settings; account restrictions also apply to
existing sessions.

## Service

Create a dedicated unprivileged `sugarwatch` account. Install application files
and dependencies in a release directory, with `/opt/sugar-watch/current` pointing
to the selected release. Create its virtual environment at `.venv`.

The account requires read access to application files. It should not own or be
able to modify the source or virtual environment. The database account requires
access only to the application database, including permissions needed for
startup table creation and migrations.

Install `deploy/sugar-watch.service` in `/etc/systemd/system/`, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sugar-watch
sudo systemctl status sugar-watch
```

The service binds to `127.0.0.1:8000`, trusts forwarded headers only from
`127.0.0.1`, uses one worker, and restarts after failures. Startup migrations run
before requests are served. Request access logs are disabled to avoid recording
OAuth callback query strings.

Configure the local proxy or tunnel to route the public HTTPS hostname to
`http://127.0.0.1:8000`, preserving the host and original HTTPS scheme. Redirect
public HTTP to HTTPS and bypass caching for application responses. Keep the
application and MySQL ports private. Validate the service on the target host.

## Backups

`deploy/backup-mysql.sh` streams a MySQL dump through gzip and GPG encryption.
It requires `mysqldump`, `gzip`, `gpg`, an existing protected output directory,
and an imported, trusted encryption recipient public key.

```bash
bash deploy/backup-mysql.sh /secure/mysql-backup.cnf /secure/backups RECIPIENT
```

Use `deploy/mysql-backup.cnf.example` as the credential-file reference and set
its permissions to `0600`. Keep the decryption key separately, copy encrypted
backups off the host, and configure retention and failure monitoring. Test a
restore to a separate database before relying on scheduled backups.

On Ubuntu, `python tests/check_backup.py` verifies backup encryption and failure
handling with fictional SQL and a disposable GPG key. It does not test a live
MySQL restore.

## Upgrades and rollback

1. Run `python scripts/check_release.py` and select a tested commit or release.
2. Build a new release directory and virtual environment without modifying the running release.
3. Stop the service, create a verified database backup, and record the current release.
4. Point `/opt/sugar-watch/current` to the new release and restart the service.
5. Verify HTTPS, authentication, account isolation, and data entry.

If an upgrade fails, stop the service and inspect whether migrations ran.
Switching application files does not reverse schema or data migrations. Restore
the pre-upgrade database backup when required before restarting the previous
release. A restore discards writes made after the backup.
