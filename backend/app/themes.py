"""Ready themes for the Mini App and the cabinet: one click in «Mini App → Тема» fills the colours and the corner
radius; everything stays editable afterwards. Light or dark follows the chosen theme."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .security import require_permission

router = APIRouter()
THEMES = {
    "corgi": {"title": "Корги (по умолчанию)", "accent": "#39ff88", "accent_2": "#22d3ee", "background": "#070b12", "surface": "#0e1522",
              "text": "#e8f1ff", "muted": "#8a99b3", "danger": "#ff5c7a", "radius": 16},
    "minimal": {"title": "Минимал", "accent": "#111827", "accent_2": "#4b5563", "background": "#ffffff", "surface": "#f3f4f6",
                "text": "#111827", "muted": "#6b7280", "danger": "#dc2626", "radius": 12},
    "private": {"title": "Приватный", "accent": "#a78bfa", "accent_2": "#7c3aed", "background": "#0b0a12", "surface": "#16141f",
                "text": "#ede9fe", "muted": "#8b85a3", "danger": "#f87171", "radius": 18},
    "buddy": {"title": "Дружелюбный", "accent": "#f59e0b", "accent_2": "#fb923c", "background": "#fff8ef", "surface": "#ffffff",
              "text": "#3a2416", "muted": "#8a6d57", "danger": "#e11d48", "radius": 22},
    "native": {"title": "Как Telegram", "accent": "#2aabee", "accent_2": "#229ed9", "background": "#17212b", "surface": "#232e3c",
               "text": "#f5f5f5", "muted": "#7f91a4", "danger": "#ef5b5b", "radius": 12},
    "terminal": {"title": "Терминал", "accent": "#00ff66", "accent_2": "#00cc52", "background": "#000000", "surface": "#0a0f0a",
                 "text": "#b6ffb6", "muted": "#5f8f5f", "danger": "#ff3355", "radius": 2},
    "magazine": {"title": "Журнал", "accent": "#b91c1c", "accent_2": "#111111", "background": "#faf7f2", "surface": "#ffffff",
                 "text": "#1c1917", "muted": "#78716c", "danger": "#b91c1c", "radius": 4},
    "neon": {"title": "Неон", "accent": "#ff2bd6", "accent_2": "#00e5ff", "background": "#0a0014", "surface": "#170528",
             "text": "#fdf4ff", "muted": "#a78bbf", "danger": "#ff4d6d", "radius": 20},
    "pop": {"title": "Поп", "accent": "#ff5a1f", "accent_2": "#ffd400", "background": "#fff1e6", "surface": "#ffffff",
            "text": "#1f1300", "muted": "#7a5c3e", "danger": "#e11d48", "radius": 26},
}


@router.get("/api/admin/app-config/themes")
async def themes(admin=Depends(require_permission("read"))):
    return {"themes": [{"id": key, **value} for key, value in THEMES.items()]}
