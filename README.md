# Keyholder

Standalone subscription backend.

Safety boundaries:
- Do not modify Marzban, Hiddify, Nginx, firewall, or existing production services.
- Do not write under /opt/marzban, /var/lib/marzban, or /opt/braavos-gateway.
- All development belongs inside /srv/keyholder.
- Bind local development API only to 127.0.0.1:18000.
- Never commit secrets.
