# Deployment preparation status

Prepared October 30, 2026. Target: Ubuntu Server VM inside a Windows host receiving security updates. No domain purchased and no public service started.

Prepared: approved Google-account restrictions and session revocation; required production host/allowlist configuration; secure-cookie and callback tests; loopback-only systemd service; isolated release runner; GitHub Actions workflow; encrypted MySQL backup script; GitHub release/update/rollback and restore instructions. The owner address is stored only in private Git-ignored environment files.

Verified locally: seven isolated application/security/production/migration check scripts; encrypted fictional backup round trip and failure handling; shell syntax; Git whitespace; unit syntax with a substituted local executable. The real production unit executable does not exist on this laptop, as expected. A credential-pattern scan of source text found no matching secrets; this is not a guarantee of a full historical secret audit. Generated Python cache was removed from Git tracking.

Still requires the PC: hardware and Windows update/ESU checks, hypervisor installation, guest installation/security updates, automatic VM startup before sign-in, live MySQL migration, backup scheduling and off-PC destination, actual service hardening/start/recovery tests.

Still requires chosen hostname/accounts: domain/DNS (or deliberate no-domain hosting choice), production Google OAuth client and exact callback, persistent Cloudflare tunnel, external HTTPS and user acceptance tests.

GitHub Actions must be observed on GitHub after publishing; local checks do not demonstrate a hosted CI result. Do not treat this as a live or fully validated server.
