"""Verify encrypted backups with fictional SQL and a disposable GPG key."""

import gzip
import os
import subprocess
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="sugar-backup-check-") as directory:
    root = Path(directory)
    home = root / "gnupg"
    home.mkdir(mode=0o700)
    out = root / "backups"
    out.mkdir(mode=0o700)
    tools = root / "bin"
    tools.mkdir()
    dump = tools / "mysqldump"
    dump.write_text('#!/bin/sh\nprintf "SELECT 1;\\n"\n')
    dump.chmod(0o700)
    config = root / "mysql.cnf"
    config.write_text("[client]\nuser=fictional\n")
    config.chmod(0o600)
    env = dict(
        os.environ, GNUPGHOME=str(home), PATH=str(tools) + ":" + os.environ["PATH"]
    )

    def run(args, **kw):
        return subprocess.run(args, env=env, capture_output=True, check=True, **kw)

    try:
        run(
            [
                "gpg",
                "--batch",
                "--pinentry-mode",
                "loopback",
                "--passphrase",
                "",
                "--quick-generate-key",
                "Backup Check <check@example.test>",
                "rsa2048",
                "encr",
                "1d",
            ]
        )
        args = [
            "bash",
            str(repo / "deploy/backup-mysql.sh"),
            str(config),
            str(out),
            "check@example.test",
        ]
        run(args)
        files = list(out.glob("*.gpg"))
        assert len(files) == 1
        data = run(["gpg", "--batch", "--decrypt", str(files[0])]).stdout
        assert gzip.decompress(data) == b"SELECT 1;\n"
        assert files[0].stat().st_mode & 0o077 == 0
        dump.write_text('#!/bin/sh\nprintf "incomplete dump"\nexit 1\n')
        result = subprocess.run(args, env=env, capture_output=True)
        assert result.returncode != 0
        assert len(list(out.glob("*.gpg"))) == 1
        assert not list(out.glob("*.partial"))
        config.chmod(0o644)
        assert subprocess.run(args, env=env, capture_output=True).returncode != 0
        # Static unit verification with the deployment-only Python path substituted.
        unit = root / "sugar-watch.service"
        text = (repo / "deploy/sugar-watch.service").read_text()
        text = text.replace(
            "/opt/sugar-watch/current/.venv/bin/python", "/usr/bin/python3"
        )
        unit.write_text(text)
        run(["systemd-analyze", "verify", str(unit)])
    finally:
        subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=env, capture_output=True)
print(
    "PASS: encrypted backup round trip; private output permissions; failed dump leaves no published/partial backup; unsafe credential permissions rejected; unit syntax verified with local Python path."
)
