> Актуальный дистрибутив: `v28.36.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

> Текущий магазин v21.5.1: [общая документация](../DOCUMENTATION.md). Ниже описаны контракты интеграции; готового проверенного VPN-движка и production-бинарников этих клиентов в релизе нет.

# VPN Shop Desktop v15

Native integration contracts for Windows (Wintun), macOS (Network Extension) and Linux (WireGuard). The desktop shell must obtain a signed profile from `/api/me/v15/bootstrap` and delegate tunnel establishment to the OS-native engine.
