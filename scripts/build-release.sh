#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# Historical release: VERSION="39.0.0-production" artifact=remnawave_vpn_shop_v39_production.zip migration=0017_v39_staging_isolation
VERSION="21.5.1"
# Previous migration head retained for compatibility: 0030_v44_5_16_privacy_and_refund_integrity
# Current migration head: 0084_subscription_freeze (the manifest reads it from Alembic below)
ARTIFACT="$(python3 -c 'import json; print(json.load(open("release-manifest.template.json"))["artifact"])')"
python -m pytest -q tests
python -m compileall -q backend
python -m pytest -q tests/test_release_quality_v2_2.py
bash -n install.sh deploy/*.sh scripts/*.sh
python - <<'PY'
import yaml
with open("docker-compose.yml") as f: yaml.safe_load(f)
PY
rm -f "$ARTIFACT" "${ARTIFACT}.sha256" "${ARTIFACT%.zip}.sha256" "${ARTIFACT%.zip}_manifest.json"
# The archive cannot safely contain its own final SHA256 manifest (that would be self-referential).
# Normalize a template first; the exact detached manifest is generated only after the ZIP is complete.
if [[ -n "${RELEASE_MANIFEST_SOURCE:-}" ]]; then
  cp "$RELEASE_MANIFEST_SOURCE" release-manifest.template.json
elif [[ -f release-manifest.json ]]; then
  cp release-manifest.json release-manifest.template.json
elif [[ -f release-manifest.template.json ]]; then
  :
else
  echo "Не найден release manifest" >&2; exit 1
fi
python - "$VERSION" "$ARTIFACT" <<'PY'
import json,sys
p='release-manifest.template.json'
m=json.load(open(p)); m['sha256']=None; m['tests']=None; m['artifact']=sys.argv[2]; m['version']=sys.argv[1]; m['migration_head']=__import__('alembic.script',fromlist=['ScriptDirectory']).ScriptDirectory('backend/alembic').get_current_head(); m['detached_manifest']=sys.argv[2].removesuffix('.zip')+'_manifest.json'; m['signed']=False
m['note']='Template only. The exact release manifest is shipped as a detached file next to the ZIP because embedding the ZIP SHA inside the ZIP is self-referential.'
json.dump(m,open(p,'w'),ensure_ascii=False,indent=2); open(p,'a').write('\n')
PY
python scripts/package-source.py "$ARTIFACT"
unzip -tq "$ARTIFACT" >/dev/null
unzip -l "$ARTIFACT" | grep '\.env.example' >/dev/null
SHA=$(sha256sum "$ARTIFACT" | awk '{print $1}')
TEST_LINE=$(python -m pytest -q tests | tail -1)
TESTS=$(printf '%s\n' "$TEST_LINE" | grep -oE '[0-9]+ passed' | awk '{print $1}')
[[ -n "$TESTS" ]] || { echo "Не удалось определить число пройденных тестов: $TEST_LINE" >&2; exit 1; }
python - "$SHA" "$VERSION" "$ARTIFACT" "$TESTS" <<'PY'
import json,sys
t='release-manifest.template.json'; out=sys.argv[3].removesuffix('.zip')+'_manifest.json'
m=json.load(open(t)); m['version']=sys.argv[2]; m['artifact']=sys.argv[3]; m['sha256']=sys.argv[1]; m['tests']=int(sys.argv[4]); m['signed']=False
m['detached_manifest']=out
m['commit']=__import__('subprocess').check_output(['git','rev-parse','HEAD']).decode().strip()
m['ci_run']=__import__('os').environ.get('RELEASE_CI_RUN','')
m['note']='Detached manifest. The ZIP intentionally does not contain its own final SHA256 manifest; use this exact detached manifest to verify the artifact.'
json.dump(m,open(out,'w'),ensure_ascii=False,indent=2); open(out,'a').write('\n')
PY
sha256sum "$ARTIFACT" | tee "${ARTIFACT}.sha256" > "${ARTIFACT%.zip}.sha256"
echo "Release: $ARTIFACT"
echo "SHA256:  $SHA"
echo "Tests:   $TESTS"
