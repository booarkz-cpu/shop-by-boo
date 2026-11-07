from pathlib import Path
ROOT=Path(__file__).parents[1]
def read(rel): return (ROOT/rel).read_text()

# The content settings never show secrets: tests/test_behaviour_plans_privacy.py (BACKLOG A1).

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
