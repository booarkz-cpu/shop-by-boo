import React, {createContext, useContext, useEffect, useLayoutEffect, useRef, useState} from "react";

export type Lang = "ru" | "en" | "uk";

export const EN: Record<string, string> = {
  "Личный кабинет": "Account",
  "Реферальная программа": "Referral program",
  "Магазин VPN": "VPN shop",
  "Вход": "Sign in",
  "Регистрация": "Sign up",
  "Электронная почта": "Email",
  "Пароль": "Password",
  "Войти": "Sign in",
  "Создать аккаунт": "Create account",
  "Уже есть аккаунт? Войти": "Already have an account? Sign in",
  "Нет аккаунта? Зарегистрироваться": "No account? Sign up",
  "Войти через Telegram": "Sign in with Telegram",
  "Войти через Яндекс": "Sign in with Yandex",
  "Войти через VK": "Sign in with VK",
  "Обзор": "Overview",
  "Тарифы": "Plans",
  "Пробный период": "Trial",
  "Подключение": "Connection",
  "Поддержка": "Support",
  "Серверы": "Servers",
  "Конструктор тарифов": "Plan builder",
  "Устройства": "Devices",
  "Трафик": "Traffic",
  "Срок": "Duration",
  "Безлимит": "Unlimited",
  "Онлайн": "Online",
  "Офлайн": "Offline",
  "Отключён": "Disabled",
  "Неизвестно": "Unknown",
  "Нет узлов": "No nodes",
  "Remnawave недоступен": "Remnawave is unavailable",
  "Статус узлов без адресов и служебных данных": "Node status without addresses or internal data",
  "Соберите тариф: устройства, трафик и срок": "Build a plan: devices, traffic and duration",
  "Подписка": "Subscription",
  "Статус": "Status",
  "Активна": "Active",
  "Неактивна": "Inactive",
  "Нет активной подписки": "No active subscription",
  "Истекает": "Expires",
  "Кошелёк": "Wallet",
  "Реферальный баланс": "Referral balance",
  "Баланс кошелька": "Wallet balance",
  "Промокод": "Promo code",
  "Оплатить": "Pay",
  "С баланса": "Pay from balance",
  "Платёж создан": "Payment created",
  "Оплачено с баланса": "Paid from balance",
  "Активировать пробный период": "Activate trial",
  "Пробный период активирован": "Trial activated",
  "дней": "days",
  "Ссылка подписки": "Subscription link",
  "Копировать ссылку": "Copy link",
  "Скопировано": "Copied",
  "Инструкции по устройствам": "Device guides",
  "Тема": "Subject",
  "Сообщение": "Message",
  "Создать тикет": "Create ticket",
  "Тикет создан": "Ticket created",
  "Выйти": "Sign out",
  "Язык": "Language",
  "Загрузка…": "Loading…",
  "Выберите тариф": "Choose a plan",
  "Провайдер оплаты": "Payment provider",
  "Сохранить": "Save",
  "Отмена": "Cancel",
  "Ошибка": "Error",
  "Разделы кабинета": "Account sections",
  "Telegram WebApp initData недоступен": "Telegram WebApp initData is unavailable",
  "Добро пожаловать": "Welcome",
  "Управляйте подпиской, тарифами и подключением": "Manage your subscription, plans and connection",
  "Безопасный доступ к сети": "Secure network access",
  "Пользовательский раздел": "Custom section",
  "Ссылка подписки пока недоступна": "Subscription link is not available yet",
  "Выберите тариф для пробного периода": "Select a plan for the trial",
  "дней бесплатно": "free days",
  "Подписка и балансы вашего аккаунта": "Your subscription and balances",
  "Выберите тариф и способ оплаты": "Choose a plan and payment method",
  "Создайте обращение в службу поддержки": "Create a support request",
  "Ссылка подписки и инструкции по устройствам": "Subscription link and device guides",
  "или": "or",
  "Код": "Code",
  "Установите совместимый VPN-клиент, импортируйте ссылку подписки и подключитесь.": "Install a compatible VPN client, import the subscription URL, then connect.",
  "Установите совместимый VPN-клиент из App Store, импортируйте ссылку подписки и подключитесь.": "Install a compatible VPN client from the App Store, import the subscription URL, then connect.",
  "Откройте VPN-клиент на ТВ, добавьте подписку по ссылке или QR и активируйте профиль.": "Open the VPN client on your TV, add the subscription via link or QR, then activate the profile.",
  "Установите клиент для Windows, импортируйте ссылку подписки и включите соединение.": "Install a Windows VPN client, import the subscription URL, then enable the connection.",
  "Установите клиент для macOS, импортируйте ссылку подписки и подключитесь.": "Install a macOS VPN client, import the subscription URL, then connect.",
  "Установите клиент для Linux, импортируйте ссылку подписки через конфиг или URI.": "Install a Linux VPN client and import the subscription URL via config or URI.",
  "Use your compatible VPN client and import the subscription URL.": "Use your compatible VPN client and import the subscription URL.",
  "Приложения": "Apps",
  "Для Android и iOS есть отдельные приложения магазина.": "Separate shop apps are available for Android and iOS.",
  "Открыть": "Open",
  "Скачать": "Download",
  "Скачать по ссылке": "Download from link",
  "Скачать подписку": "Download subscription",
  "Контрольная сумма": "Checksum",
};

export const UK: Record<string, string> = {
  "Личный кабинет": "Особистий кабінет",
  "Реферальная программа": "Реферальна програма",
  "Магазин VPN": "Магазин VPN",
  "Вход": "Вхід",
  "Регистрация": "Реєстрація",
  "Электронная почта": "Електронна пошта",
  "Пароль": "Пароль",
  "Войти": "Увійти",
  "Создать аккаунт": "Створити акаунт",
  "Уже есть аккаунт? Войти": "Вже є акаунт? Увійти",
  "Нет аккаунта? Зарегистрироваться": "Немає акаунта? Зареєструватися",
  "Войти через Telegram": "Увійти через Telegram",
  "Войти через Яндекс": "Увійти через Яндекс",
  "Войти через VK": "Увійти через VK",
  "Обзор": "Огляд",
  "Тарифы": "Тарифи",
  "Пробный период": "Пробний період",
  "Подключение": "Підключення",
  "Поддержка": "Підтримка",
  "Серверы": "Сервери",
  "Конструктор тарифов": "Конструктор тарифів",
  "Устройства": "Пристрої",
  "Трафик": "Трафік",
  "Срок": "Термін",
  "Безлимит": "Безліміт",
  "Онлайн": "Онлайн",
  "Офлайн": "Офлайн",
  "Отключён": "Вимкнено",
  "Неизвестно": "Невідомо",
  "Нет узлов": "Немає вузлів",
  "Remnawave недоступен": "Remnawave недоступний",
  "Статус узлов без адресов и служебных данных": "Статус вузлів без адрес і службових даних",
  "Соберите тариф: устройства, трафик и срок": "Зберіть тариф: пристрої, трафік і термін",
  "Подписка": "Підписка",
  "Статус": "Статус",
  "Активна": "Активна",
  "Неактивна": "Неактивна",
  "Нет активной подписки": "Немає активної підписки",
  "Истекает": "Спливає",
  "Кошелёк": "Гаманець",
  "Реферальный баланс": "Реферальний баланс",
  "Баланс кошелька": "Баланс гаманця",
  "Промокод": "Промокод",
  "Оплатить": "Оплатити",
  "С баланса": "З балансу",
  "Платёж создан": "Платіж створено",
  "Оплачено с баланса": "Сплачено з балансу",
  "Активировать пробный период": "Активувати пробний період",
  "Пробный период активирован": "Пробний період активовано",
  "дней": "днів",
  "Ссылка подписки": "Посилання підписки",
  "Копировать ссылку": "Копіювати посилання",
  "Скопировано": "Скопійовано",
  "Инструкции по устройствам": "Інструкції для пристроїв",
  "Тема": "Тема",
  "Сообщение": "Повідомлення",
  "Создать тикет": "Створити тікет",
  "Тикет создан": "Тікет створено",
  "Выйти": "Вийти",
  "Язык": "Мова",
  "Загрузка…": "Завантаження…",
  "Выберите тариф": "Виберіть тариф",
  "Провайдер оплаты": "Провайдер оплати",
  "Сохранить": "Зберегти",
  "Отмена": "Скасувати",
  "Ошибка": "Помилка",
  "Разделы кабинета": "Розділи кабінету",
  "Telegram WebApp initData недоступен": "Telegram WebApp initData недоступний",
  "Добро пожаловать": "Ласкаво просимо",
  "Управляйте подпиской, тарифами и подключением": "Керуйте підпискою, тарифами та підключенням",
  "Безопасный доступ к сети": "Безпечний доступ до мережі",
  "Пользовательский раздел": "Користувацький розділ",
  "Ссылка подписки пока недоступна": "Посилання підписки поки недоступне",
  "Выберите тариф для пробного периода": "Виберіть тариф для пробного періоду",
  "дней бесплатно": "днів безкоштовно",
  "Подписка и балансы вашего аккаунта": "Підписка та баланси вашого акаунта",
  "Выберите тариф и способ оплаты": "Виберіть тариф і спосіб оплати",
  "Создайте обращение в службу поддержки": "Створіть звернення до служби підтримки",
  "Ссылка подписки и инструкции по устройствам": "Посилання підписки та інструкції для пристроїв",
  "или": "або",
  "Код": "Код",
  "Установите совместимый VPN-клиент, импортируйте ссылку подписки и подключитесь.": "Встановіть сумісний VPN-клієнт, імпортуйте посилання підписки та підключіться.",
  "Установите совместимый VPN-клиент из App Store, импортируйте ссылку подписки и подключитесь.": "Встановіть сумісний VPN-клієнт з App Store, імпортуйте посилання підписки та підключіться.",
  "Откройте VPN-клиент на ТВ, добавьте подписку по ссылке или QR и активируйте профиль.": "Відкрийте VPN-клієнт на ТБ, додайте підписку за посиланням або QR і активуйте профіль.",
  "Установите клиент для Windows, импортируйте ссылку подписки и включите соединение.": "Встановіть клієнт для Windows, імпортуйте посилання підписки та увімкніть з'єднання.",
  "Установите клиент для macOS, импортируйте ссылку подписки и подключитесь.": "Встановіть клієнт для macOS, імпортуйте посилання підписки та підключіться.",
  "Установите клиент для Linux, импортируйте ссылку подписки через конфиг или URI.": "Встановіть клієнт для Linux, імпортуйте посилання підписки через конфіг або URI.",
  "Use your compatible VPN client and import the subscription URL.": "Використайте сумісний VPN-клієнт і імпортуйте посилання підписки.",
  "Приложения": "Застосунки",
  "Для Android и iOS есть отдельные приложения магазина.": "Для Android і iOS є окремі застосунки магазину.",
  "Открыть": "Відкрити",
  "Скачать": "Завантажити",
  "Скачать по ссылке": "Завантажити за посиланням",
  "Скачать подписку": "Завантажити підписку",
  "Контрольная сумма": "Контрольна сума",
};


let activeLang: Lang = "ru";

Object.assign(EN, {"Открыть переписку": "Open conversation", "Закрыть переписку": "Close conversation", "Загрузка переписки…": "Loading conversation…", "Ожидает ответа поддержки": "Waiting for support", "Ответ получен": "Reply received", "Поддержка": "Support", "Вы": "You", "Клиент": "Customer", "Повторить загрузку": "Retry loading", "Загрузить следующие сообщения": "Load next messages", "Сообщение отправлено": "Message sent", "Отправить сообщение": "Send message", "Ваш ответ снова откроет обращение. Переписка сохранится.": "Your reply will reopen the ticket. The conversation is saved.", "Последний ответ поддержки": "Latest support reply"});
Object.assign(EN, {
  "Кошелёк": "Wallet",
  "Моя подписка": "My subscription",
  "Подарки": "Gifts",
  "Уведомления": "Notifications",
  "Баланс кошелька": "Wallet balance",
  "Сумма пополнения": "Top-up amount",
  "Способ оплаты": "Payment method",
  "Пополнить": "Top up",
  "История платежей": "Payment history",
  "Операции кошелька": "Wallet transactions",
  "Активировать подарок": "Redeem a gift",
  "Подарочный код": "Gift code",
  "Подарить подписку": "Give a subscription",
  "Купить в подарок": "Buy as a gift",
  "Мои подарки": "My gifts",
  "Скопировать код": "Copy code",
  "Ваш код приглашения": "Your referral code",
  "Запросить выплату": "Request a withdrawal",
  "Реквизиты": "Payment details",
  "Мои выплаты": "My withdrawals",
  "Начисления": "Rewards",
  "Активные сессии": "Active sessions",
  "Выйти на всех устройствах": "Sign out everywhere",
  "История входов": "Sign-in history",
  "События безопасности": "Security events",
  "Прочитано": "Mark as read",
  "Новое обращение": "New support request",
  "Мои обращения": "My requests",
  "Тема": "Subject",
  "Сообщение": "Message",
  "Отправить": "Send",
  "Ответ поддержки": "Support reply",
  "Обновить данные": "Reload data",
  "Изменения сохранены": "Changes saved",
  "Ваш личный кабинет": "Your account",
  "Сервис временно недоступен": "Service temporarily unavailable",
  "Активировать подарочную карту": "Redeem a gift card",
  "Код карты": "Card code",
  "Зачислить на баланс": "Credit to wallet",
  "Скопировать ссылку приглашения": "Copy referral link",
  "Ожидает выдачи": "Awaiting access",
  "Выдан": "Access granted",
  "Ошибка выдачи": "Access delivery failed",
  "Активирована": "Redeemed",
  "Готов к передаче": "Ready to share",
  "Решено": "Resolved",
  "Записей пока нет": "No records yet",
  "Главная": "Home",
  "Найти раздел…": "Find a section…",
  "Найти раздел": "Find a section",
  "Клиенты магазина": "Shop customers",
  "Пользователи VPN": "VPN users",
  "Обращения клиентов": "Customer requests",
  "Платёжные агенты": "Payment agents",
  "Функции и модули": "Features and modules",
  "Защита и 2FA": "Security and 2FA",
  "Роли и администраторы": "Roles and administrators",
  "Резервные копии": "Backups",
  "Настройка магазина": "Shop setup",
  "Обслуживание": "Maintenance",
  "Открыть": "Open",
  "К списку": "Back to list",
  "Клиенты не найдены": "No customers found",
  "Найти": "Search",
  "Открытые": "Open",
  "Решённые": "Resolved",
  "Все": "All",
  "Отправить ответ": "Send reply",
  "Не удалось загрузить раздел": "Unable to load this section",
  "Повторить загрузку": "Retry",
  "Клиент": "Customer",
  "Статус": "Status",
  "Показать": "Show"
});

Object.assign(EN, {
  "Объединение аккаунтов": "Merge accounts",
  "Сначала создайте код в аккаунте, данные которого нужно перенести. Затем войдите в основной аккаунт, вставьте код и проверьте план переноса. Запись выполняется только после подтверждения обеих сторон.": "First create a code in the account whose data you want to transfer. Then sign in to the primary account, paste the code, and review the transfer plan. Nothing is written until both sides are confirmed.",
  "1. Создать код в исходном аккаунте": "1. Create a code in the source account",
  "Текущий пароль исходного аккаунта": "Current source-account password",
  "Для аккаунта без пароля оставьте поле пустым и войдите заново не более пяти минут назад.": "For an account without a password, leave this empty and make sure you signed in within the last five minutes.",
  "Создать одноразовый код": "Create one-time code",
  "Одноразовый код": "One-time code",
  "Скопировать код": "Copy code",
  "2. Проверить код в основном аккаунте": "2. Review the code in the primary account",
  "Код исходного аккаунта": "Source-account code",
  "Вставьте код после входа в аккаунт, который должен остаться основным.": "Paste the code after signing in to the account that should remain primary.",
  "Показать план переноса": "Show transfer plan",
  "Исходный аккаунт": "Source account",
  "Основной аккаунт": "Primary account",
  "Ключи доступа": "Passkeys",
  "Способы входа": "Sign-in methods",
  "Конфликты": "Conflicts",
  "Текущий пароль основного аккаунта": "Current primary-account password",
  "Для аккаунта без пароля оставьте поле пустым и используйте свежий вход.": "For an account without a password, leave this empty and use a recent sign-in.",
  "Я проверил план и подтверждаю необратимый перенос данных в текущий аккаунт.": "I reviewed the plan and confirm the irreversible transfer into the current account.",
  "Объединить аккаунты": "Merge accounts",
  "Объединение пока невозможно. Устраните перечисленные конфликты.": "The accounts cannot be merged yet. Resolve the listed conflicts first.",
  "Не удалось создать код объединения": "Could not create a merge code",
  "Не удалось проверить объединение": "Could not validate the merge",
  "Не удалось объединить аккаунты": "Could not merge the accounts"
});

const TABLES: Record<Exclude<Lang, "ru">, Record<string, string>> = {en: EN, uk: UK};

export function translate(lang: Lang, value: string): string {
  if (!value || lang === "ru") return value;
  const table = TABLES[lang];
  if (table && table[value]) return table[value];
  if (lang === "uk") {
    // Ukrainian shares the Russian source strings; fall back to English only when
    // no Ukrainian entry exists, so an untranslated label never renders as Russian.
    if (EN[value]) return EN[value];
    return value;
  }
  const active = value.match(/^Активна до (.+)$/);
  if (active) return `Active until ${active[1]}`;
  const days = value.match(/^(.*) · (.*) дней$/);
  if (days) return `${days[1]} · ${days[2]} days`;
  const status = value.match(/^Статус: (.+)$/);
  if (status) return `Status: ${status[1]}`;
  const balance = value.match(/^Баланс: (.+)$/);
  if (balance) return `Balance: ${balance[1]}`;
  const wallet = value.match(/^Баланс кошелька: (.+)$/);
  if (wallet) return `Wallet balance: ${wallet[1]}`;
  const expires = value.match(/^Истекает: (.+)$/);
  if (expires) return `Expires: ${expires[1]}`;
  const trial = value.match(/^Пробный период · (.+) дней$/);
  if (trial) return `Trial · ${trial[1]} days`;
  const online = value.match(/^Онлайн (\d+) из (\d+)$/);
  if (online) return `Online ${online[1]} of ${online[2]}`;
  return value;
}

export function t(value: string): string {
  return translate(activeLang, value);
}

const LangContext = createContext<{lang: Lang; setLang: (lang: Lang) => void}>({lang: "ru", setLang: () => undefined});

export function detectLang(serverDefault?: string): Lang {
  const stored = localStorage.getItem("rw_lang");
  if (stored === "en" || stored === "ru" || stored === "uk") return stored;
  if (serverDefault === "en" || serverDefault === "ru" || serverDefault === "uk") return serverDefault;
  const browser = navigator.language?.toLowerCase() ?? "";
  // uk/ua before en: a Ukrainian browser locale ("uk-UA") must not fall through to ru.
  if (browser.startsWith("uk") || browser.startsWith("ua")) return "uk";
  return browser.startsWith("en") ? "en" : "ru";
}

export function LangProvider({children}: {children: React.ReactNode}) {
  const [lang, setLangState] = useState<Lang>(detectLang());
  useEffect(() => {
    activeLang = lang;
    document.documentElement.lang = lang;
  }, [lang]);
  function setLang(next: Lang) {
    activeLang = next;
    localStorage.setItem("rw_lang", next);
    setLangState(next);
  }
  return <LangContext.Provider value={{lang, setLang}}>{children}</LangContext.Provider>;
}

export function useLang() {
  return useContext(LangContext);
}

function sourceOf(current: string, stored: string | undefined, lang: Lang): string {
  if (stored && (current === stored || current === translate("en", stored) ||
      current === translate("uk", stored) || current === translate("ru", stored))) return stored;
  return current;
}

export function DomLocalizer({children}: {children: React.ReactNode}) {
  const ref = useRef<HTMLDivElement>(null);
  const {lang} = useLang();
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes: Text[] = [];
    let current: Node | null = walker.nextNode();
    while (current) {
      nodes.push(current as Text);
      current = walker.nextNode();
    }
    for (const node of nodes) {
      const value = node.nodeValue ?? "";
      const extra = node as Text & {__i18nSource?: string};
      const source = sourceOf(value, extra.__i18nSource, lang);
      extra.__i18nSource = source;
      const next = translate(lang, source);
      if (node.nodeValue !== next) node.nodeValue = next;
    }
    root.querySelectorAll<HTMLElement>("[aria-label]").forEach((el) => {
      const label = el.getAttribute("aria-label") || "";
      const stored = el.dataset.i18nAria;
      const source = sourceOf(label, stored, lang);
      el.dataset.i18nAria = source;
      const next = translate(lang, source);
      if (label !== next) el.setAttribute("aria-label", next);
    });
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input,textarea").forEach((el) => {
      const source = sourceOf(el.placeholder || "", el.dataset.i18nPlaceholder, lang);
      el.dataset.i18nPlaceholder = source;
      const next = translate(lang, source);
      if (el.placeholder !== next) el.placeholder = next;
    });
  });
  return <div ref={ref} style={{display: "contents"}}>{children}</div>;
}
