#!/usr/bin/env bash
set -e
echo "== NUGET TEST SUITE =="

BASE="http://localhost:8080"

# 1. root service doc
echo -n "[root] "
curl -s -o /dev/null -w "%{http_code}\n" $BASE/

# 2. packages feed
echo -n "[feed] "
curl -s $BASE/Packages | grep -q "<feed" && echo "OK" || echo "FAIL"

# 3. git search (exact)
echo -n "[git exact] "
curl -s "$BASE/Packages?\$filter=Id%20eq%20'git.install'" | grep -q "git.install" && echo "OK" || echo "FAIL"

# 4. git search (substring)
echo -n "[git fuzzy] "
curl -s "$BASE/Packages?\$filter=substringof('git',tolower(Id))" | grep -q "git.install" && echo "OK" || echo "FAIL"

# 5. 7zip search
echo -n "[7zip] "
curl -s "$BASE/Packages?\$filter=Id%20eq%20'7zip.install'" | grep -q "7zip.install" && echo "OK" || echo "FAIL"

# 6. find by id endpoint
echo -n "[find endpoint] "
curl -s "$BASE/FindPackagesById()?id='git.install'" | grep -q "git.install" && echo "OK" || echo "FAIL"

# 7. download headers git
echo -n "[download git] "
curl -s -I $BASE/package/git.install/2.54.0 | grep -q "200 OK" && echo "OK" || echo "FAIL"

# 8. download headers 7zip
echo -n "[download 7zip] "
curl -s -I $BASE/package/7zip.install/26.0.0 | grep -q "200 OK" && echo "OK" || echo "FAIL"

# 9. empty search safety
echo -n "[empty search] "
curl -s "$BASE/Packages?\$filter=Id%20eq%20'doesnotexist'" | grep -q "<feed" && echo "OK" || echo "FAIL"

echo "== DONE =="