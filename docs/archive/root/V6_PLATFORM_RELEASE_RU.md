# VPN Shop by Corgi — Unified Platform v6

## Реализовано
- Corgi Command Center: единая сводка пользователей, подписок, выручки, billing/security/fraud и node-agent сигналов.
- Event Bus: доменные события фиксируются в неизменяемом audit trail с request_id; UI просмотра событий.
- Node Orchestrator: health evaluation, drain actions, approval gate, auto-heal policy. Опасные действия не исполняются без явной настройки.
- Capacity Planning: нагрузка node agents, thresholds, capacity recommendation.
- Provisioning intents: provider/region/template/dry-run API. Реальное создание VPS требует credentials конкретного provider adapter.
- Revenue Intelligence: 30-day revenue/MRR proxy, ARPU, active subscriptions, referrals, coupons/campaigns.
- Security Operations Center: security incidents + fraud signals + approval policy.
- Public Status API: агрегирует StatusComponent без раскрытия внутренних секретов.
- Public API / Webhooks Center: использует существующие ShopApiKey и OutboundWebhook как единый источник истины.
- Multi-tenant/white-label control-plane configuration: workspaces/branding/currency config подготовлен без дублирования основной БД.
- Retention, localization, approval, status-page и orchestrator policies доступны через единый config API.
- Corgi Intelligence: evidence-based рекомендации из billing/security/fraud/capacity сигналов без автономного destructive execution.
- Support Pro остаётся единственным операционным центром поддержки.

## Намеренно gated
Hetzner/DigitalOcean/AWS/Vultr provisioning, реальные push/email provider sends, налоговые документы и внешние accounting integrations требуют credentials/юридической конфигурации конкретного production окружения. В проекте для них создан control-plane и intent/gating слой; успешное внешнее действие не симулируется.

## Архитектурный принцип
Новые функции используют существующие User/Subscription/Payment/UserDevice/NodeAgent/AgentAction/FeatureFlag/ShopApiKey/OutboundWebhook/AutomationRule/StatusComponent/AuditLog вместо параллельных дублирующих таблиц.
