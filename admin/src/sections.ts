/**
 * Map of the admin panel: every section, its group, its menu name and a
 * one-sentence description of what the administrator does there.
 *
 * The menu, the "All sections" hub, page headers and quick search all read
 * from this list, so a section's name and description are written once.
 * Groups follow the order an operator works in: numbers first, then
 * customers, sales, marketing, the bot and cabinet, servers, system and
 * security.
 */
export type SectionItem<T extends string = string> = {
  tab: T;
  label: string;
  description: string;
  /** Extra words for search: synonyms, old names, provider names. */
  keywords?: string;
};

export type SectionGroup<T extends string = string> = {
  id: string;
  title: string;
  description: string;
  items: SectionItem<T>[];
};

export const SECTION_GROUPS = [
  {
    id: "analytics",
    title: "Аналитика",
    description: "Продажи, выручка и состояние магазина",
    items: [
      {tab: "dashboard", label: "Главная", description: "Сводка за сутки и месяц: клиенты, подписки, выручка, серверы и то, что требует внимания.", keywords: "обзор дашборд"},
      {tab: "analytics", label: "Аналитика продаж", description: "Выручка, конверсия, средний чек и динамика продаж по периодам.", keywords: "статистика отчёты"},
      {tab: "retention", label: "Удержание клиентов", description: "Когорты по месяцу первой оплаты, повторные покупки, LTV и причины отмены подписки.", keywords: "ltv когорты отток churn retention"},
      {tab: "financial", label: "Финансовый журнал", description: "Неизменяемый журнал всех денежных операций: оплаты, возвраты, бонусы и выплаты.", keywords: "ledger бухгалтерия"},
      {tab: "opsReadiness", label: "Запуск и оповещения", description: "Что осталось настроить перед приёмом оплат и куда приходят оповещения о сбоях.", keywords: "готовность запуск алерты оповещения telegram"},
      {tab: "health", label: "Состояние системы", description: "Работают ли API, база данных, Redis, Remnawave и фоновые процессы.", keywords: "health здоровье"},
      {tab: "incidents", label: "Инциденты", description: "Сбои и проблемы: открыть инцидент, отметить решение, посмотреть историю.", keywords: "аварии"},
    ],
  },
  {
    id: "users",
    title: "Пользователи",
    description: "Клиенты, их устройства и обращения",
    items: [
      {tab: "crm", label: "Клиенты магазина", description: "Поиск клиента по ID, Telegram, имени или email и полная карточка: подписка, баланс, платежи, действия.", keywords: "crm пользователи карточка"},
      {tab: "users", label: "Пользователи VPN", description: "Учётные записи в Remnawave: статус, имя пользователя и дата создания.", keywords: "remnawave"},
      {tab: "devices", label: "Устройства", description: "Устройства клиентов (HWID): сколько подключено и какие можно отключить.", keywords: "hwid"},
      {tab: "customerOperations", label: "Импорт и массовые операции", description: "Перенос клиентов из другого бота и действия сразу над группой клиентов.", keywords: "импорт миграция массовые"},
      {tab: "support", label: "Обращения клиентов", description: "Вопросы клиентов из бота и кабинета: ответить, назначить, закрыть.", keywords: "тикеты поддержка"},
      {tab: "supportPro", label: "Support Pro", description: "Состояние отдельного центра поддержки: очереди, операторы, каналы и SLA.", keywords: "поддержка email"},
    ],
  },
  {
    id: "tariffs",
    title: "Тарифы и оплата",
    description: "Что продаём, за сколько и как принимаем оплату",
    items: [
      {tab: "plans", label: "Тарифы", description: "Готовые тарифы: название, срок, цена, трафик и число устройств.", keywords: "планы цены"},
      {tab: "constructor", label: "Конструктор тарифов", description: "Тариф, который клиент собирает сам: устройства, трафик и срок с ценой за каждый пункт.", keywords: "калькулятор"},
      {tab: "trafficPackages", label: "Пакеты трафика", description: "Дополнительные гигабайты, которые клиент докупает к действующей подписке.", keywords: "гигабайты докупка"},
      {tab: "subscriptionOperations", label: "Изменения подписок", description: "Продления, смены тарифа и докупки: что запросил клиент и чем закончилось.", keywords: "апгрейд продление"},
      {tab: "payments", label: "Платежи", description: "Все оплаты клиентов со статусом, суммой и платёжной системой.", keywords: "транзакции"},
      {tab: "providers", label: "Платёжные агенты", description: "Подключённые платёжные системы, их доступность и доля успешных оплат.", keywords: "провайдеры yookassa stripe"},
      {tab: "refunds", label: "Возвраты", description: "Заявки на возврат денег: проверить, одобрить или отклонить.", keywords: "refund"},
      {tab: "family", label: "Семейные подписки", description: "Семьи владельцев тарифов с местами: участники и их синхронизация с Remnawave.", keywords: "семья family приглашение"},
      {tab: "gifts", label: "Подарки", description: "Подарочные коды на подписку: создать код, задать срок и число активаций.", keywords: "подарочные коды"},
      {tab: "staging", label: "Проверка платежей", description: "Тестовые оплаты в sandbox платёжных систем перед запуском магазина.", keywords: "sandbox тест e2e"},
    ],
  },
  {
    id: "marketing",
    title: "Маркетинг",
    description: "Акции, рассылки и вовлечение клиентов",
    items: [
      {tab: "marketing", label: "Акции и рассылки", description: "Скидочные акции, промокоды, рекламные блоки и рассылки в Telegram.", keywords: "промокоды реклама broadcast"},
      {tab: "offers", label: "Группы и предложения", description: "Группы клиентов по условиям и персональные предложения для каждой группы.", keywords: "сегменты аудитории"},
      {tab: "giveaways", label: "Конкурсы и призы", description: "Розыгрыши и призы: условия участия, победители и выдача наград.", keywords: "розыгрыш"},
      {tab: "surveys", label: "Опросы", description: "Вопросы клиентам в боте и кабинете и сводка ответов.", keywords: "анкеты"},
      {tab: "payouts", label: "Рефералы и партнёры", description: "Реферальная программа (уровни и проценты), партнёры со своей ставкой, сверка балансов и заявки на вывод вознаграждения.", keywords: "партнёры рефералы реферальная программа уровни вывод выплаты"},
      {tab: "notifications", label: "Уведомления", description: "Отправленные клиентам уведомления и состояние push для Android и iOS.", keywords: "push fcm apns"},
      {tab: "pages", label: "Новости и страницы", description: "Новости, инструкции и правовые страницы для бота и кабинета.", keywords: "контент статьи оферта"},
    ],
  },
  {
    id: "storefront",
    title: "Бот и кабинет",
    description: "Что видит клиент в Telegram, кабинете и приложениях",
    items: [
      {tab: "content", label: "Меню бота и Mini App", description: "Тексты бота, кнопки главного меню, экран Mini App и инструкции по подключению.", keywords: "тексты кнопки telegram"},
      {tab: "menuTree", label: "Дерево кнопок", description: "Вложенные меню бота: порядок кнопок, подменю и действия по нажатию.", keywords: "меню"},
      {tab: "appConfig", label: "Конфигурация Mini App", description: "Тема, акции, серверы, способы пополнения, рефералы, поддержка, документы и оферта Mini App.", keywords: "mini app конфиг тема stars оферта сбп"},
      {tab: "botBanners", label: "Баннеры бота", description: "Картинки над разделами бота и Mini App: стандартные с корги Люси или свои.", keywords: "баннер картинка изображение start"},
      {tab: "cabinet", label: "Личный кабинет", description: "Вкладки веб-кабинета клиента: порядок, названия и собственные страницы.", keywords: "веб-кабинет вкладки"},
      {tab: "apps", label: "Android и iOS", description: "Приложения магазина: версии, файлы для загрузки и ссылки на сторы.", keywords: "apk мобильные"},
      {tab: "branding", label: "Оформление", description: "Название магазина, логотип, иконка сайта, цвета и тема по умолчанию.", keywords: "брендинг логотип тема"},
    ],
  },
  {
    id: "servers",
    title: "Серверы",
    description: "Узлы Remnawave, сеть и нагрузка",
    items: [
      {tab: "nodes", label: "Серверы", description: "Узлы Remnawave: онлайн, нагрузка, трафик и число подключённых клиентов.", keywords: "ноды узлы remnawave"},
      {tab: "networkIntel", label: "Сеть узлов: ASN и репутация", description: "В чьих сетях стоят узлы и не попали ли их адреса в списки злоупотреблений.", keywords: "asn abuseipdb ripestat ip"},
      {tab: "nodeTerminal", label: "Терминал узлов", description: "Командная оболочка на VPN-сервере через агент: с подтверждением 2FA и записью сессии.", keywords: "ssh shell консоль терминал сниппеты"},
      {tab: "routing", label: "Маршрутизация", description: "Выбор узла для клиента по задержке и нагрузке.", keywords: "smart routing балансировка"},
      {tab: "capacity", label: "Планирование мощности", description: "Прогноз нагрузки: когда узлам не хватит ресурсов и сколько добавить.", keywords: "capacity прогноз"},
      {tab: "orchestrator", label: "Оркестратор", description: "Автоматическое включение и вывод узлов по правилам нагрузки.", keywords: "orchestrator"},
      {tab: "torrents", label: "Торренты на узлах", description: "Кто из клиентов качает торренты: счётчики срабатываний Xray без адресов, отметка в антиабузе и уведомление.", keywords: "bittorrent p2p dht utp торрент"},
      {tab: "platform", label: "Антиабуз и агенты", description: "Агенты на узлах, блокировка устройств-нарушителей и вебхуки событий.", keywords: "abuse hwid агенты"},
      {tab: "monitoring", label: "Мониторинг", description: "Проверки доступности, версии компонентов и рабочие процессы.", keywords: "uptime"},
    ],
  },
  {
    id: "system",
    title: "Система",
    description: "Настройки, фоновые задачи и обновления",
    items: [
      {tab: "runtimeSettings", label: "Настройки без перезапуска", description: "Параметры магазина, платёжных систем и интеграций, которые применяются сразу.", keywords: "конфигурация env"},
      {tab: "features", label: "Функции и модули", description: "Включение и выключение отдельных возможностей магазина.", keywords: "флаги feature"},
      {tab: "plugins", label: "Плагины", description: "Установка подписанных плагинов, их права и журнал работы.", keywords: "расширения"},
      {tab: "automation", label: "Автоматизация", description: "Правила «событие → действие» и автоматические кампании.", keywords: "campaign rules"},
      {tab: "workers", label: "Фоновые процессы", description: "Worker и планировщик: работают ли, когда последний раз отвечали.", keywords: "worker"},
      {tab: "jobs", label: "Очередь задач", description: "Фоновые задачи: ожидают, выполняются, завершились ошибкой; повтор вручную.", keywords: "очередь jobs"},
      {tab: "mailDomain", label: "Почтовый домен: SPF, DKIM, DMARC", description: "Доходят ли письма магазина: DNS-записи домена и отчёты DMARC о том, кто отправляет почту от его имени.", keywords: "почта email mx spf dkim dmarc доставляемость"},
      {tab: "operations", label: "Диагностика", description: "Проверка конфигурации, подключений и готовности к работе с подсказками по исправлению.", keywords: "проверка"},
      {tab: "releases", label: "Обновления", description: "Установленная версия, доступные выпуски и история обновлений.", keywords: "релизы версии github"},
      {tab: "deployments", label: "Развёртывания", description: "Постепенный выпуск новой версии: доля трафика и ошибки.", keywords: "canary"},
      {tab: "enterprise", label: "Корпоративный контур", description: "Проверки, кампании и правила автоматизации для крупных установок.", keywords: "enterprise"},
      {tab: "intelligence", label: "Рекомендации", description: "Подсказки по росту продаж и снижению нагрузки на основе данных магазина.", keywords: "советы"},
    ],
  },
  {
    id: "security",
    title: "Безопасность",
    description: "Доступ к панели, защита и резервные копии",
    items: [
      {tab: "security", label: "Защита и 2FA", description: "Двухфакторный вход, смена пароля и правила доступа к панели.", keywords: "пароль totp"},
      {tab: "passkeys", label: "Ключи доступа", description: "Вход в панель по ключу доступа (passkey) вместо пароля.", keywords: "webauthn"},
      {tab: "admins", label: "Роли и администраторы", description: "Кто имеет доступ к панели и с какими правами.", keywords: "доступ права сотрудники"},
      {tab: "sessions", label: "Сессии", description: "Активные входы в панель; завершить чужую или все сессии.", keywords: "входы"},
      {tab: "fraud", label: "Антифрод", description: "Подозрительные оплаты и аккаунты: проверить и принять решение.", keywords: "мошенничество"},
      {tab: "audit", label: "Журнал действий", description: "Кто из администраторов, когда и что изменил.", keywords: "аудит лог"},
      {tab: "backups", label: "Резервные копии", description: "Расписание и хранение копий базы, ручной запуск и проверка.", keywords: "backup"},
      {tab: "recovery", label: "Восстановление", description: "Восстановление из копии и проверка готовности к аварии.", keywords: "restore"},
    ],
  },
] as const satisfies readonly SectionGroup[];

export type SectionTab = (typeof SECTION_GROUPS)[number]["items"][number]["tab"];

/** Sections that open from other pages but have no menu item of their own. */
export const EXTRA_SECTIONS: SectionItem[] = [
  {tab: "panel", label: "Все разделы", description: "Все функции панели по группам с описанием. Начните вводить название, чтобы найти раздел."},
  {tab: "v3", label: "Центр управления", description: "Сводка по узлам, устройствам и автоматизации."},
  {tab: "customer360", label: "Карточка клиента", description: "Подробные данные клиента."},
  {tab: "command360", label: "Командный центр", description: "Сводка всех систем магазина в реальном времени."},
  {tab: "commercial", label: "Коммерческие показатели", description: "Выручка и удержание клиентов."},
  {tab: "integrations", label: "Интеграции", description: "Подключённые внешние сервисы и их состояние."},
  {tab: "events", label: "События", description: "Поток событий магазина."},
  {tab: "soc", label: "Центр безопасности", description: "Сигналы безопасности и реакции на них."},
  {tab: "status", label: "Статус сервиса", description: "Состояние компонентов для страницы статуса."},
];

export function sectionInfo(tab: string): {item?: SectionItem; group?: SectionGroup} {
  for (const group of SECTION_GROUPS as readonly SectionGroup[]) {
    const item = group.items.find((entry) => entry.tab === tab);
    if (item) return {item, group};
  }
  return {item: EXTRA_SECTIONS.find((entry) => entry.tab === tab)};
}

export function matchesSection(item: SectionItem, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return `${item.label} ${item.description} ${item.keywords || ""}`.toLowerCase().includes(needle);
}
