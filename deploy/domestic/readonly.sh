#!/bin/sh
set -eu
case "${SSH_ORIGINAL_COMMAND:-status}" in
    status) exec sudo -n /usr/local/lib/keyholder-admin/gate_status.py ;;
    backup) exec sudo -n /usr/local/libexec/keyholder-gate-backup ;;
    *) exit 126 ;;
esac
