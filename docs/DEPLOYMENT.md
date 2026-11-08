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
| `USDA_API_KEY` | Optional server-side FoodData Central API key. |

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
its permissions to `0600`. Use an account authorized to read tables, views,
triggers, routines, and events. The application's restricted database account
may not have sufficient permissions; do not expand its privileges solely for
backups. Keep the decryption key separately, copy encrypted
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


## Storage migrations and LibreView imports

Startup migrations add unique indexes for one active health profile per user,
one favorite per user/food pair, and one imported glucose reading per user and
provider key. Inactive profiles are preserved. Existing duplicate groups block
the migration with a table name and group count; no winner is chosen automatically.
Test migrations against a restored copy before upgrading. MySQL DDL commits
separately; retries check existing columns and indexes before creating them.

The Glucose page accepts English LibreView CSV exports using the existing
authenticated HTTPS route. Select the export's timezone and date order.
Files must fit within the 4 MB request limit, including multipart overhead.
Ambiguous daylight-saving timestamps and nonnumeric readings are rejected for
review. The whole file is validated before insertion. Repeated uploads skip
existing imported readings, including soft-deleted ones. Permanent deletion
removes the import key, so a later upload can reintroduce a deleted reading.

## Automatic LibreLinkUp collection

The optional connector uses an unofficial LibreLinkUp interface. It runs as a
separate systemd service and requires outbound HTTPS and database access.
Configure a dedicated LibreLinkUp follower account, accept the sharing
invitation, and complete verification and consent in the official app.
Confirm that the follower sees the intended person's readings.

Use `deploy/libre-sync.env.example` to create `/etc/sugar-watch/libre-sync.env`,
owned by `root:sugarwatch` with mode `0640`. Set the exact application user ID,
LibreLinkUp patient ID, region, and compatible app version. Keep credentials
outside the repository and release archives.

For interactive setup, run:

```bash
python scripts/setup_libre.py
```

Setup hides the password, lists shared connections and active application
accounts, and fetches readings without importing them. The resulting private
configuration is stored at `~/.config/sugar-watch/libre-sync.env` with mode `0600`.
Verify the account mapping on the target deployment before installing that
configuration at the production path. User IDs can differ between databases.

Test collection with the protected environment loaded:

```bash
python scripts/sync_libre.py --dry-run
```

Alternatively, `--env-file /private/path/libre-sync.env` loads an owner-only
configuration. A dry run can update private session state but does not write
database records. Install the service and timer templates, then enable collection:

```bash
sudo install -m 0644 deploy/sugar-watch-libre-sync.service /etc/systemd/system/
sudo install -m 0644 deploy/sugar-watch-libre-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sugar-watch-libre-sync.timer
```

The timer runs every five minutes with up to 15 seconds of jitter. Session
tickets are reused until expiry, with at most one renewal for an expired
authentication response. Token state is stored in the owner-only systemd state
directory `/var/lib/sugar-watch-libre-sync`. A lock prevents overlapping fetches.
HTTP 429 responses honor `Retry-After` with a minimum 15-minute cooldown. Failed
requests back off from 15 minutes to six hours, or longer if the provider requires
it. Successful requests clear the cooldown. No passwords, tokens, or raw glucose
values are logged.

Check collection with:

```bash
systemctl list-timers sugar-watch-libre-sync.timer
journalctl -u sugar-watch-libre-sync.service
```

Failure notifications require separate host monitoring. LibreLinkUp exposes
about 12 hours of history; longer outages may require a CSV backfill. CSV and
live-feed sampling intervals can differ. Exact overlapping timestamp/value pairs
are skipped across sources. The integration is not a real-time clinical monitor,
and provider changes can require updates. See the
[integration reference](https://github.com/timoschlueter/nightscout-librelink-up)
and [official sharing setup](https://librelinkup.com/articles/getting-started).

## FoodData Central

Obtain an API key from [USDA](https://fdc.nal.usda.gov/api-key-signup/).
Use `USDA_API_KEY` in the protected application environment. For deployments
loading a private `.env`, the interactive setup command verifies and saves the key:

```bash
python scripts/setup_usda.py
```

Restart the web service after changing configuration. For systemd deployments
using `/etc/sugar-watch/app.env`, place the setting in that environment file.
Keep the key out of Git, browser code, and request logs. Do not use the shared
demonstration key for production.

Food search is authenticated and limited to ten results per page. Users review
nutrition before saving a food definition; saving does not log a meal. Imported
nutrition uses a 100 g reference basis, and missing nutrients remain unknown.
Save requests require CSRF and an account-bound signed review valid for 30
minutes. Repeated saves preserve existing food edits. Deleted foods must be
restored explicitly. Logged meal snapshots remain unchanged.

USDA receives search terms, not account IDs or health history. Provider errors
are sanitized. Custom foods and existing meal logging remain available if the
API is unavailable. See the [API guide](https://fdc.nal.usda.gov/api-guide/) for
provider limits and [third-party notices](../THIRD_PARTY_NOTICES.md) for attribution.

## Release bundles

Build a tested source bundle:

```bash
python scripts/check_release.py
python scripts/package_release.py
```

The bundle includes current source, including uncommitted changes, a commit
reference, and file checksums. Credentials, database exports, virtual
environments, and backups are excluded. Prefer a clean committed checkout for
published releases. Transfer bundles through a trusted channel; checksums detect
corruption but do not establish publisher identity.

`deploy/update-server.sh` supports the standard `/opt/sugar-watch/current`
layout described above. Configure `/etc/sugar-watch/server-deploy.conf` using
`deploy/server-deploy.conf.example`, owned by root with mode `0600`. The updater
requires an existing installation, a working encrypted backup configuration,
and a trusted encryption recipient. Adapt service paths before using a different
installation layout.

Unpack a bundle in a new directory and run:

```bash
tar -xzf /path/to/sugar-watch-RELEASE.tar.gz
sudo bash sugar-watch-release/deploy/update-server.sh "$PWD/sugar-watch-release"
```

The updater verifies the manifest, builds a separate release environment, and
runs isolated checks before stopping services. It pauses collection, makes an
encrypted backup, switches the release, and checks local application startup.
The timer's previous active state is preserved; updates do not initially enable it.
A failure after switching leaves services stopped for inspection. The previous
release path is saved in `PREVIOUS_RELEASE`. Verify external HTTPS, Google
sign-in, account isolation, and the latest sync result after updating.


## Apple Health imports and Shortcuts

The Apple Health page uses Apple's free native ZIP export for existing history
and workouts. It accepts only the original export.zip, streams at most 100 MB
to a temporary file, and validates the full supported XML before committing.
The expanded XML limit is 1 GB, with bounded records and entity declarations
rejected. Temporary files are closed after success, error, or disconnect.
Unrelated categories and GPS routes are not imported. Native exports preserve
individual supported samples and source names; repeated native exports are
deduplicated. The source export is not retained.

Apple Shortcuts can send sleep, steps, active energy, body weight, heart rate,
resting heart rate, and HRV. The app provides an authenticated, manual iPhone
build guide; no signed one-tap shortcut is distributed. A Mac is needed for
Apple's supported command-line signing process. Do not advertise an unsigned
file as installable. Complete workout history still uses the native ZIP.

The plan/batch/complete endpoints are exact POST paths under
`/integrations/apple-health/shortcuts/`. They require the existing hashed,
revocable, account-scoped bearer credential; browser cookies cannot authorize
them. Other browser requests, including native-import, still require the
signed-in account and CSRF. The legacy JSON import endpoint remains compatible
with existing connections but is not needed by the new user workflow.

Plans bind account, token, category, dates, and expected starting checkpoint,
and expire after 24 hours. They cover at most two days, with a one-day overlap
for late samples. Initial routine sync starts two days back; the ZIP supplies
older history. Batches contain at most 200 individual samples. Delivery receipts
make repeat requests safe. A checkpoint advances only after all numbered batches
and the declared sample count match. Missing/failed batches leave it unchanged.
Old delivery receipts expire after 30 days. Saved samples are not expired.
Idle categories return up_to_date for 20 hours, avoiding repeated Health queries.
No background phone polling or unlimited retry loop is required.

The phone recipe checks Wi-Fi before network access, and uses a charger trigger
after manual testing. A Wi-Fi name check is not a transport guarantee if Wi-Fi
drops; the server cannot verify the route. Airplane Mode with Wi-Fi re-enabled
is the documented strict no-cellular option. Locked-device Health access and
background execution are controlled by iOS. Users must build/test the shortcut
and grant Health permissions on the actual iPhone. No real-device execution is
implied by the server and browser checks.

The new repeat-safe migration adds health_shortcut_progress,
health_shortcut_batches, and health_native_imports without changing existing
samples. Per-account writes are serialized. Large native imports use one atomic
database transaction and can take several minutes. Review logs locally without
printing raw health records, request bodies, or authorization headers.

## Public verified-email membership

Email signup is disabled by default. Static ALLOWED_EMAILS bootstrap accounts
remain valid. Database-approved verified addresses are also permitted, and all
browser sessions, health uploads, and Libre account checks use the same policy.
New approvals do not grant administrative access or access to other accounts.
Closing new registration does not revoke previously approved memberships.

Configure sending privately with `python scripts/setup_email.py` from the staged
release. A dedicated Gmail account can use smtp.gmail.com:587 with STARTTLS and
an App Password after 2-Step Verification. Other authenticated TLS SMTP services
are supported. The wizard checks SMTP authentication without sending a message,
then atomically writes owner-only .env settings. Do not paste SMTP credentials
into chat, commit them, or use the normal Gmail password. PUBLIC_BASE_URL must
be the exact HTTPS origin on an allowed host; links never use request Host data.

The /join page sends a 30-minute, single-use verification link. Only its SHA-256
hash is retained. Opening a link with GET does not approve the email: the user
must submit a CSRF-protected confirmation. The verification page strips the path and query from
referrers and removes its secret query from application access-log formatting.
Tokens expire when used or superseded. Email is limited per address, per source
IP hash, and globally (200 requests/day); SMTP failures still consume reservations.
Delivery bodies and secrets must not be logged. Send-limit responses do not reveal
whether an address already has an account. Mail is not a durable job queue: failed
delivery is reported and the user can request another link after the cooldown.

Google remains the authentication provider after verification. The address must
be associated with a Google Account. Check the Google OAuth audience/publishing
configuration: an app left in Testing can reject people who are not test users,
even after Sugar Watch approves their email. Do not expand OAuth scopes simply
to send verification mail. SMTP is configured separately.

The repeat-safe migration adds email_approvals and email_verifications without
changing existing users. Explicitly revoked database approvals cannot be restored
by public email verification. Static bootstrap access is managed through the
deployment allowlist, and user.active still applies to all access paths.
Actual SMTP delivery, mailbox reception/spam placement, and public Google login
must be tested after provider setup; mocked checks do not establish delivery.
