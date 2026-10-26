#!/usr/bin/env python3
"""Telegram chat pictures of the bot for README: real banners and the bot's own texts.

The bot cannot be photographed without a live Telegram account, so this renders a faithful
Telegram (dark theme, 390x844 phone) chat: the user's command, the bot's photo message with
the section banner from backend/app/assets/bot_banners, its caption and inline buttons.
Texts follow backend/app/bot.py and bot_workspace.py with demo values.

    python3 scripts/screenshots/bot_chat.py [out-dir]   # default: docs/img
"""
import base64
import html
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANNERS = ROOT / "backend/app/assets/bot_banners"
sys.path.insert(0, str(ROOT / "scripts/bot-banners"))
from render import sticker  # noqa: E402  the bot avatar is corgi Lusi from the sticker sheets
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/img"

CHATS = {
    "bot-start": ("/start", "start", "<b>Добро пожаловать в Корги Люси!</b>\n\n🔥 <b>Осенняя скидка</b> −25% на все тарифы\n\n💳 <b>Актуальные цены</b>\n• Месяц: <s>199.00 ₽</s> <b>149.25 ₽</b>\n• Три месяца: <s>499.00 ₽</s> <b>374.25 ₽</b>\n• Год: <s>1690.00 ₽</s> <b>1267.50 ₽</b>",
                  [["🛒 Открыть магазин"], ["🎁 Пробный период", "💬 Поддержка"], ["📚 Инструкции"]]),
    "bot-balance": ("/balance", "balance", "<b>Кошелёк</b>\nКошелёк: 350.00 RUB", [["💳 Кошелёк"]]),
    "bot-buy": ("/buy", "buy", "🛒 <b>Тарифы</b>\n• Месяц — 199.00 RUB / 30 дн.\n• Три месяца — 499.00 RUB / 90 дн.\n• Год — 1690.00 RUB / 365 дн.", [["🛒 Открыть магазин"]]),
    "bot-support": ("/support", "support", "<b>Поддержка</b>", [["💬 Поддержка"]]),
}


def uri(path: pathlib.Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def avatar() -> str:
    import io
    buf = io.BytesIO()
    sticker("support", outline=0).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def page(command: str, banner: str, caption: str, rows) -> str:
    keyboard = "".join('<div class="row">' + "".join(f'<div class="btn">{html.escape(b)}<span class="wa">↗</span></div>' for b in row) + "</div>" for row in rows)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}} body{{margin:0;width:390px;height:844px;font:15.5px/1.38 -apple-system,'Segoe UI',Roboto,Inter,sans-serif;color:#fff;
background:radial-gradient(circle at 20% 30%,#1a2735 0,transparent 40%),radial-gradient(circle at 80% 70%,#1b2a3a 0,transparent 45%),#0e1621;overflow:hidden}}
.top{{height:58px;background:#17212b;display:flex;align-items:center;gap:12px;padding:0 14px;border-bottom:1px solid #0b1118}}
.back{{font-size:24px;color:#8dabc9}} .ava{{width:40px;height:40px;border-radius:50%;background:#fff7e8 url({avatar()}) 50% 22%/170% no-repeat}}
.name b{{display:block;font-size:16px}} .name span{{font-size:13px;color:#7f91a4}}
.chat{{padding:12px 10px;display:flex;flex-direction:column;gap:8px;height:calc(844px - 58px - 54px);justify-content:flex-end}}
.me{{align-self:flex-end;background:#2b5278;padding:7px 12px;border-radius:16px 16px 4px 16px;font-size:15.5px}} .me small{{color:#7db1e0;margin-left:8px;font-size:12px}}
.msg{{align-self:flex-start;width:330px;background:#182533;border-radius:16px 16px 16px 4px;overflow:hidden}}
.msg img{{width:100%;display:block}} .cap{{padding:8px 11px 6px;white-space:pre-wrap}} .cap s{{color:#8ea3b8}}
.time{{text-align:right;color:#6d8296;font-size:12px;padding:0 10px 6px}}
.kb{{width:330px;display:flex;flex-direction:column;gap:5px}} .row{{display:flex;gap:5px}}
.btn{{flex:1;position:relative;background:rgba(24,37,51,.92);border-radius:10px;padding:10px 8px;text-align:center;font-weight:600;font-size:14.5px}}
.wa{{position:absolute;right:6px;top:3px;font-size:10px;color:#8dabc9}}
.input{{position:absolute;bottom:0;left:0;right:0;height:54px;background:#17212b;display:flex;align-items:center;gap:10px;padding:0 12px;color:#6d8296}}
.menu{{background:#2f6ea5;color:#fff;border-radius:16px;padding:6px 12px;font-weight:600;font-size:14px}}
</style></head><body>
<div class="top"><span class="back">←</span><div class="ava"></div><div class="name"><b>Корги Люси</b><span>бот</span></div></div>
<div class="chat"><div class="me">{html.escape(command)}<small>12:00 ✓✓</small></div>
<div class="msg"><img src="{uri(BANNERS / (banner + '.jpg'), 'image/jpeg')}"><div class="cap">{caption}</div><div class="time">12:00</div></div>
<div class="kb">{keyboard}</div></div>
<div class="input"><span class="menu">☰ Меню</span><span>Сообщение</span></div>
</body></html>"""


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        tab = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        for name, (command, banner, caption, rows) in CHATS.items():
            tab.set_content(page(command, banner, caption, rows))
            tab.wait_for_function("[...document.images].every(i => i.complete)")
            tab.screenshot(path=str(OUT / f"{name}.png"))
            print("saved", OUT / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main()
