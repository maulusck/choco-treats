#!/usr/bin/env bash
set -e
exec sh -c 'trap "exit" INT; while :;do l=/var/log/apache2/error.log;[ "$1" = -a ]&&l="$l /var/log/apache2/access.log"; podman exec -lit sh -c "tail -f $l"; sleep 1; clear;done' sh "$1"