#!/usr/bin/env python3
"""Stream a restored domestic archive between verified SSH hosts; no laptop copy."""

import argparse
import re
import shlex
import subprocess
from pathlib import Path

ARCHIVE = (
    "/var/lib/keyholder-recovery/downloaded/var/lib/keyholder-recovery/bundle/nodes/domestic.tar"
)
RECEIVE = """import hashlib, pathlib, sys, tempfile, os
root=pathlib.Path('/var/lib/keyholder-recovery');root.mkdir(mode=0o700,parents=True,exist_ok=True)
dest=root/'domestic.tar'
assert not dest.exists(), 'Archive already exists; inspect before retrying'
fd,name=tempfile.mkstemp(prefix='.domestic-',dir=root)
h=hashlib.sha256();size=0
try:
 with os.fdopen(fd,'wb') as out:
  while chunk:=sys.stdin.buffer.read(65536):
   size+=len(chunk);assert size <= 160*1024**2, 'Archive exceeds limit'
   h.update(chunk);out.write(chunk)
 assert size>1024 and h.hexdigest()==sys.argv[1], 'Archive checksum mismatch'
 os.link(name,dest)
 print('Domestic archive transferred and verified on target; no laptop file created.')
finally:
 pathlib.Path(name).unlink(missing_ok=True)
"""


def transfer(source: str, target: str, config: str) -> None:
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host) for host in [source, target]):
        raise ValueError("Use SSH aliases with letters, digits, dots, underscores or hyphens")
    ssh = [
        "ssh",
        "-F",
        config,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=3",
    ]
    digest = subprocess.check_output(
        [*ssh, source, "sudo -n sha256sum " + ARCHIVE], text=True, timeout=30
    ).split()[0]
    if not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("Source checksum unavailable")
    with subprocess.Popen(
        [*ssh, source, "sudo -n cat " + ARCHIVE], stdout=subprocess.PIPE
    ) as reader:
        assert reader.stdout is not None
        try:
            result = subprocess.run(
                [*ssh, target, "sudo -n python3 -c " + shlex.quote(RECEIVE) + " " + digest],
                stdin=reader.stdout,
                timeout=180,
            )
        except BaseException:
            reader.kill()
            reader.wait()
            raise
        finally:
            reader.stdout.close()
        if reader.wait(timeout=15) or result.returncode:
            raise ValueError("Transfer failed; inspect target before retrying")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("foreign_alias")
    parser.add_argument("domestic_alias")
    parser.add_argument("--ssh-config", default=str(Path.home() / ".ssh/config"))
    args = parser.parse_args()
    transfer(args.foreign_alias, args.domestic_alias, args.ssh_config)
