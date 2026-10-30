# Sugar Watch: Ubuntu VM deployment

Status: prepared on the development laptop; not deployed. Use Ubuntu Server 24.04 LTS with Python 3.12. Windows must still receive security updates. A VM does not protect its contents from a compromised host.

## Before leaving the laptop

- Choose a domain/subdomain and initial approved Google email addresses.
- Review all uncommitted work, including the earlier application changes. Do not blindly stage everything.
- Never commit .env, Google secrets, tunnel tokens, SQL dumps, health data or backups. Check already tracked files too: ignore rules do not untrack files or erase Git history. Rotate any previously published credentials.
- Run the isolated checks below, review the diff and commit the reviewed source. Create and push a release tag for that exact commit. The repository remote is currently spelled `orgin`; use `git remote -v` before pushing rather than assuming `origin`.

```bash
.venv/bin/python scripts/check_release.py
git diff --check
```

## Windows and VM setup (at the PC)

Verify Windows edition, active security update coverage, CPU virtualization and available RAM before selecting VirtualBox or Hyper-V. Use a supported hypervisor version. Start with 2 virtual CPUs, 4 GB guest RAM and 40 GB disk if host capacity permits. Use NAT, disable shared clipboard/drag-and-drop/shared folders and leave router inbound ports closed. Enable host disk encryption where supported. Configure headless VM startup before Windows sign-in; the exact method depends on the chosen hypervisor. Test after a complete reboot. Disable sleep and configure power recovery.

Install Ubuntu, security updates and unattended security updates. Keep SSH disabled unless needed; do not publish SSH through the website tunnel. Configure Ubuntu firewall to deny incoming connections while permitting outgoing connections. Allow any administration traffic only through a separately secured management path. Schedule host, guest and hypervisor updates.

## First Ubuntu installation

These commands are for a fresh VM. Run as an administrator using sudo. Substitute YOUR_DEPLOY_USER with the Ubuntu account used for deployments.

```bash
sudo apt update
sudo apt install python3-venv python3-pip git mysql-server unattended-upgrades
sudo adduser --system --group --no-create-home sugarwatch
sudo install -d -o YOUR_DEPLOY_USER -g sugarwatch -m 0750 /opt/sugar-watch/releases
sudo install -d -o root -g sugarwatch -m 0750 /etc/sugar-watch
```

Clone GitHub into a separate deployment checkout using a read-only deploy key for a private repository. Never copy your laptop's personal SSH private key to the server. Choose a tested release tag, verify its commit ID and create a release directory, for example `/opt/sugar-watch/releases/v1`. Export tracked files from that commit using `git archive TAG | tar -x -C /opt/sugar-watch/releases/v1` from the checkout. Replace TAG and v1 deliberately. Keep the service account unable to modify its source code.

```bash
cd /opt/sugar-watch/releases/v1
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Create the MySQL database and an account restricted to this database and local connections. Use a unique password; do not put it in shell history. Current startup creates tables and applies migrations, so database-specific CREATE/ALTER/INDEX plus normal SELECT/INSERT/UPDATE/DELETE privileges may be necessary. Do not grant global privileges. Keep MySQL bound to loopback and confirm it is not listening publicly. If importing existing data, complete the migration below before first app startup.

Copy `deploy/production.env.example` to `/etc/sugar-watch/app.env`, owned root:sugarwatch with mode 0640. Replace every placeholder. URL-encode special characters in the database URL password. Generate SECRET_KEY using `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` and store it only in this file. Use exact comma-separated Google addresses in ALLOWED_EMAILS. Restart the app after changing this file. Development may leave the list empty; production cannot.

Register `https://YOUR_HOST/auth/google/callback` as an authorized redirect URI in a Google Web OAuth client. Use a separate production client from laptop development. Configure Google's consent/audience settings for the intended users. Use the exact public hostname in ALLOWED_HOSTS (no scheme/path). Production Google sign-in requires a verified email. Accounts remain identified by Google's stable subject identifier. Each approved user has their own data; this does not add viewer sharing.

Give the service group read/traverse access to the completed release, then install the service:

```bash
sudo chgrp -R sugarwatch /opt/sugar-watch/releases/v1
sudo chmod -R g+rX,o-rwx /opt/sugar-watch/releases/v1
sudo ln -s /opt/sugar-watch/releases/v1 /opt/sugar-watch/current
sudo cp deploy/sugar-watch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sugar-watch
sudo systemctl status sugar-watch
```

The service uses one worker because startup runs database migrations. It listens only on 127.0.0.1:8000 and trusts forwarded headers only from the local tunnel. It disables request access logs to avoid recording OAuth callback query strings. Inspect errors with `sudo journalctl -u sugar-watch`; treat any logs as potentially sensitive. Do not enable development reload. systemd hardening must be verified on the actual VM.

## Public HTTPS

Install cloudflared using Cloudflare's official Ubuntu instructions. Create a persistent, remotely managed tunnel; install its connector as a system service INSIDE Ubuntu. Keep its token out of GitHub and protect local credentials. Route the chosen public hostname to `http://127.0.0.1:8000`. Preserve the public Host header and HTTPS forwarded scheme. Enable HTTP-to-HTTPS redirection at Cloudflare. Do not configure port forwarding or publish MySQL/8000. Bypass CDN caching for the entire app; do not add cache-everything rules. Cloudflare terminates public TLS and processes website traffic, so account for that when choosing a health-data hosting provider. Consider an additional Cloudflare Access email policy if desired; test both access and Google OAuth together.

References:
- https://developers.cloudflare.com/tunnel/get-started/
- https://uvicorn.dev/settings/
- https://developers.google.com/identity/openid-connect/openid-connect

## Move the database

Stop writes to the laptop app for the final transfer. Identify the actual source MySQL location first; never assume it is on the laptop. Back up using a database administrator account with `mysqldump --single-transaction --no-tablespaces --routines --triggers --events -u BACKUP_USER -p sugar_watch > sugar-watch.sql`. It prompts for the password. Ensure all tables use a transactional engine, and avoid schema changes during the dump. Transfer through an encrypted channel into a protected directory outside the repo; import using `mysql -u ADMIN_USER -p sugar_watch < sugar-watch.sql`. Never use actual health data for GitHub CI. Startup runs existing recorded migrations; inspect errors and verify history before enabling public traffic. Never run laptop and server as independent live copies after cutover.

## Backups and restore

Schedule database dumps with a dedicated backup account and a mode-0600 MySQL option file rather than passwords on command lines. Encrypt backups and copy them off the PC with versioned retention. Back up `/etc/sugar-watch/app.env` separately in encrypted storage. Monitor backup failure and disk space. VM snapshots are supplemental, not a replacement for database backups. Before launch, restore a backup into a separate non-public database and verify accounts, row counts, timestamps, units and histories. The scheduled destination, encryption key management and retention must be configured on the PC; they are not automated by this guide.

## Future GitHub updates

1. Develop and test on the laptop, commit reviewed source and push a release tag. Never edit application code directly on the live server.
2. On Ubuntu, fetch tags in the deployment checkout. Verify the exact tag/commit. Export it into a NEW release directory and build a NEW venv there. Do not replace the live environment with pip installs.
3. Run isolated checks in that release with test credentials and no production database configuration. Do not import main.py against production as a harmless smoke test: imports run migrations.
4. Stop `sugar-watch`, take and verify a fresh database backup, and record the current release path and database version. This causes a brief maintenance window.
5. Point `/opt/sugar-watch/current` to the new release using `sudo ln -sfn /opt/sugar-watch/releases/NEW_RELEASE /opt/sugar-watch/current` after confirming current is a symlink. Start the service and inspect errors.
6. Verify login, save/edit/restore, isolation and HTTPS from an external network. Keep the previous release until the new one is proven.
7. If deployment fails, stop the service. Check whether migrations ran before selecting rollback. Compatible changes may only require repointing the symlink; incompatible schema/data changes require restoring the pre-update backup as well. Restoration loses writes made after that backup, so keep access closed until the decision is made. Never assume switching code reverses migrations.

## Launch acceptance checks

- Host, guest and hypervisor security updates are current; Windows has active coverage.
- Backup restore and post-reboot automatic startup succeed without interactive login.
- External HTTP redirects to HTTPS; Google callback uses the exact HTTPS address.
- Approved verified Google account can sign in and save data; an unapproved account cannot.
- Removed ALLOWED_EMAILS entry cannot reuse an existing signed-in session after restart.
- Two approved users cannot access each other's records.
- Port 8000 and MySQL are not publicly reachable; no router forwards were added.
- Production API documentation is disabled, secure session cookie is set, sensitive responses are not cached.
- Tested release commit and backup location are recorded, and a rollback path exists.

## Files prepared before buying a domain

- `scripts/check_release.py` runs each isolated check in a separate process with dummy credentials and an empty test allowlist. Use this runner even if your laptop .env restricts real access to your account.
- `.github/workflows/checks.yml` runs those checks on GitHub pushes and pull requests without production secrets or MySQL access. Confirm its first hosted run after pushing. Configure branch protection to require it in GitHub if your plan/repository supports that.
- `tests/check_production.py` tests the real production configuration using a disposable database and an example HTTPS hostname. It does not exercise actual TLS termination or Google account interaction.
- `deploy/backup-mysql.sh` streams a dump through gzip and GPG without writing plaintext. Supply a mode-0600 MySQL option file, an existing protected backup directory and an imported/trusted GPG recipient. Verify the recipient fingerprint independently, and keep its private decryption key off the server with a recovery copy. Test decryption and restoration before scheduling. The template is `deploy/mysql-backup.cnf.example`. Install gpg on Ubuntu. Schedule backups only after configuring permissions, off-PC delivery, retention and failure notifications.

Nothing here purchases a domain, creates cloud services or opens a public tunnel. Hostname, real production OAuth credentials, a real database transfer, backup destination, host update coverage and VM boot testing remain server setup tasks. The prepared private `.env.production` is not automatically loaded: install its completed contents as `/etc/sugar-watch/app.env` on the server.

## Optional local backup verification

On Ubuntu/WSL with gpg and systemd-analyze installed, run `.venv/bin/python tests/check_backup.py`. This creates a disposable encryption key and fictional SQL stream in a temporary directory. It checks encryption/decryption, output permissions, dump failures, unsafe credential-file permissions and unit syntax with a substituted local Python path. It does not connect to MySQL or install/start a service. Verify an actual MySQL restore separately on the PC.
