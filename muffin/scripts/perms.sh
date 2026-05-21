#!/bin/sh
set -e
find . -type d -exec chmod 755 {} +
find . -type f -exec chmod 644 {} +
find scripts/ -type f -exec chmod 755 {} +
find bin/ -type f -exec chmod 755 {} +