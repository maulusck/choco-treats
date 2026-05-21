#!/usr/bin/env bash
set -e

sudo apt update
sudo apt install -y mono-complete wget

mkdir -p bin

wget -q https://dist.nuget.org/win-x86-commandline/v5.11.0/nuget.exe -O bin/nuget.exe

printf '%s\n' '#!/usr/bin/env bash' \
'mono "$(dirname "$0")/nuget.exe" "$@"' > bin/nuget

chmod +x bin/nuget

echo "OK"