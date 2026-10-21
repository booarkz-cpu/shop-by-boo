from pathlib import Path

root=Path(__file__).resolve().parents[1]
main=(root/"cabinet/src/main.tsx").read_text()
css=(root/"cabinet/src/style.css").read_text()
compose=(root/"docker-compose.yml").read_text()
caddy=(root/"deploy/Caddyfile").read_text()
checks={
"cabinet_service": "  cabinet:" in compose,
"email_register": "/api/auth/register" in main,
"vk_oauth": "/api/auth/vk" in main,
"yandex_oauth": "/api/auth/yandex" in main,
"responsive": "@media (max-width: 720px)" in css and "@media (min-width: 960px)" in css,
"design_tokens": "--primary-rgb:" in css and "--radius:" in css and "#090d16" in css,
"cabinet_domain": "{$CABINET_DOMAIN}" in caddy,
"security_headers": "Content-Security-Policy" in caddy,
"no_duplicate_article": main.count("</article>") > 0 and "</article>\n                      </article>" not in main,
}
for k,v in checks.items(): print(f"{k}: {'PASS' if v else 'FAIL'}")
raise SystemExit(0 if all(checks.values()) else 1)
