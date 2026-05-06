#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:8080"
FAIL=0

GREEN="\033[0;32m"
RED="\033[0;31m"
NC="\033[0m"

ok()  { printf "%-28s ${GREEN}OK${NC}\n" "$1"; }
fail() { printf "%-28s ${RED}FAIL${NC}\n" "$1"; FAIL=1; }

http() {
  local name=$1 url=$2
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  [[ "$code" == "200" ]] && ok "$name" || { echo "  HTTP $code"; fail "$name"; }
}

xml() {
  local name=$1 url=$2 xpath=$3
  curl -s "$url" | xq -x "$xpath" >/dev/null 2>&1 && ok "$name" || fail "$name"
}

nuget_has() {
  local name=$1 term=$2
  ./bin/nuget search "$term" -Source "$BASE/Packages" -NonInteractive 2>/dev/null \
    | tr -d '\r' \
    | grep -qi "$name" && ok "nuget $term" || fail "nuget $term"
}

echo "== NUGET TESTS =="

xml "metadata" "$BASE/" "//collection[@href='Packages']"
xml "feed" "$BASE/Packages" "//*[local-name()='feed']"
xml "count" "$BASE/Packages" "//*[local-name()='count']"

xml "git exact" "$BASE/Packages?\$filter=Id%20eq%20'git.install'" \
"//*[local-name()='Id'][text()='git.install']"

xml "git fuzzy" "$BASE/Packages?\$filter=substringof('git',tolower(Id))" \
"//*[local-name()='Id']"

xml "7zip exact" "$BASE/Packages?\$filter=Id%20eq%20'7zip.install'" \
"//*[local-name()='Id'][text()='7zip.install']"

xml "find id" "$BASE/FindPackagesById()?id='git.install'" \
"//*[local-name()='Id'][text()='git.install']"

http "download git" "$BASE/package/git.install/2.54.0"
http "download 7zip" "$BASE/package/7zip.install/26.0.0"

xml "missing safe" "$BASE/Packages?\$filter=Id%20eq%20'doesnotexist'" \
"//*[local-name()='feed']"

echo ""
echo "== NUGET CLI =="

nuget_has "git.install" "git"
nuget_has "7zip.install" "7zip"

echo ""
[[ "$FAIL" -eq 0 ]] && echo -e "${GREEN}ALL PASS${NC}" || echo -e "${RED}$FAIL FAILURES${NC}"
exit $FAIL