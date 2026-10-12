"""Generate a private panel-prefix gateway snippet; never print its entry URL."""

import argparse
import json
import os
import re
import secrets
from pathlib import Path


def render(hostname: str, prefix: str, upstream: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", hostname):
        raise ValueError("Invalid hostname")
    if not re.fullmatch(r"/manage-[A-Za-z0-9_-]{32,80}", prefix):
        raise ValueError("Invalid entry prefix")
    if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", upstream):
        raise ValueError("Panel must remain on loopback")
    return f"""# Include in http. The prefix is an access secret; keep this file private.
map $http_upgrade $panel_connection {{ default upgrade; '' close; }}
limit_req_zone $server_name zone=panel_login:1m rate=10r/m;
server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name {hostname};
    ssl_certificate /etc/nginx/certs/origin.pem;
    ssl_certificate_key /etc/nginx/certs/origin.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    access_log off;
    error_log /dev/null crit;
    add_header Cache-Control "private, no-store" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Robots-Tag "noindex, nofollow" always;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $panel_connection;
    proxy_set_header Accept-Encoding "";
    proxy_connect_timeout 3s;
    proxy_read_timeout 60s;
    proxy_cache off;
    proxy_max_temp_file_size 0;
    sub_filter_once off;
    sub_filter_types application/javascript text/javascript text/css;
    sub_filter '/statics/' '{prefix}/statics/';
    sub_filter '/api/' '{prefix}/api/';
    sub_filter '<title>Marzban</title>' '<title>Management</title>';
    sub_filter 'content="Marzban"' 'content="Management"';
    location = / {{ root /usr/share/nginx/html; try_files /index.html =404; }}
    location = {prefix} {{ return 302 {prefix}/; }}
    location = {prefix}/ {{ proxy_pass http://{upstream}/dashboard/; }}
    location = {prefix}/api/admin/token {{
        limit_req zone=panel_login burst=10 nodelay;
        limit_req_status 429;
        proxy_pass http://{upstream}/api/admin/token;
    }}
    location ^~ {prefix}/ {{
        rewrite ^{prefix}/(.*)$ /$1 break;
        proxy_pass http://{upstream};
    }}
    location / {{ return 404; }}
}}
server {{
    listen 80;
    listen [::]:80;
    server_name {hostname};
    location = / {{ return 308 https://{hostname}/; }}
    location / {{ return 404; }}
}}
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hostname", required=True)
    p.add_argument("--upstream", default="127.0.0.1:8000")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--access-file", type=Path, required=True)
    args = p.parse_args()
    prefix = "/manage-" + secrets.token_urlsafe(32)
    conf = render(args.hostname, prefix, args.upstream)
    created: list[Path] = []
    try:
        for path, content in [
            (args.output, conf),
            (
                args.access_file,
                json.dumps(
                    {
                        "hostname": args.hostname,
                        "panel_url": f"https://{args.hostname}{prefix}/",
                        "active": False,
                        "authentication": "panel_login",
                        "public_delivery_verified": False,
                    }
                )
                + "\n",
            ),
        ]:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "w") as f:
                f.write(content)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    print("Private gateway and access files generated. Validate before activating.")


if __name__ == "__main__":
    main()
