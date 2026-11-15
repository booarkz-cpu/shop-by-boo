from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
checks = {
    'support source': (ROOT/'services/support-pro/app/main.py').exists(),
    'support dockerfile': (ROOT/'services/support-pro/app/Dockerfile').exists(),
    'support compose': 'support_pro:' in (ROOT/'docker-compose.yml').read_text(),
    'support caddy': '{$SUPPORT_PRO_DOMAIN}' in (ROOT/'infrastructure/reverse-proxy/Caddyfile').read_text(),
    'support sso endpoint': '/sso' in (ROOT/'services/support-pro/app/main.py').read_text(),
    'admin support api': '/api/admin/services/support-pro/status' in (ROOT/'services/backend/app/v3_api.py').read_text(),
    'admin support ui': 'SupportProDesk' in (ROOT/'apps/lucy-admin/web/src/main.tsx').read_text(),
}
for py in [ROOT/'services/backend/app/v3_api.py', ROOT/'services/support-pro/app/main.py']:
    ast.parse(py.read_text())
print('Support Pro integration audit')
for k,v in checks.items(): print(('PASS' if v else 'FAIL'), k)
if not all(checks.values()): raise SystemExit(1)
