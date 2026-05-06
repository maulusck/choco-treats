#!/usr/bin/env bash
set -e
exec sh -c "while :; do podman exec -lit sh -c 'tail -f /var/log/apache2/error.log' ; sleep 1; clear; done"