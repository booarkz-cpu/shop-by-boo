from main_source import main_source
from pathlib import Path
ROOT=Path(__file__).parents[1]
def read(rel): return (ROOT/rel).read_text()

def test_admin_content_never_returns_raw_all_settings():
    s=main_source(); part=s[s.index('async def admin_content'):s.index('async def admin_setting')]
    assert 'select(AppSetting).where(AppSetting.key.in_(safe_keys|secret_keys))' in part
    assert 'setting_values={x.key:x.value for x in ss if x.key in safe_keys}' in part
    assert '"settings":setting_values,"secret_status":secret_status' in part

def test_menu_urls_are_https_only_and_typed():
    import pytest
    from pydantic import ValidationError
    from app.main import MenuIn
    from app.menu_tree import telegram_keyboard
    from types import SimpleNamespace
    with pytest.raises(ValidationError):MenuIn(title='Bad',item_type='javascript')
    rows=[SimpleNamespace(id=i,title='Unsafe',item_type='url',action=url,parent_id=None,enabled=True,sort_order=0,style='default',icon_custom_emoji_id=None,icon='') for i,url in enumerate(['http://example.com','javascript:alert(1)'],1)]
    assert telegram_keyboard(rows,[]).inline_keyboard==[]


def test_miniapp_buttons_are_bounded_and_field_references_validated():
    import pytest
    from fastapi import HTTPException
    from app.menu_tree import normalize_mini_buttons
    for buttons in [[{'title':'Plans','type':'plans'}]*31,[{'title':'Field','type':'field','field_key':'missing'}]]:
        with pytest.raises(HTTPException):normalize_mini_buttons(buttons,set())
