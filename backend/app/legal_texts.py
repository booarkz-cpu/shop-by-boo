"""v28.73 (stage 14): drafts of the public offer, the privacy policy and the terms of use under Russian law.

The texts describe what the shop really does (plans, trial, auto-renewal, freeze, refunds through the gateways,
receipts, the data it keeps and for how long). Placeholders in braces are filled from «Реквизиты продавца»
(``legal_docs.py``). The Russian text is the legally binding one; the English and Ukrainian texts are translations
for convenience and say so.

These are drafts written by the agent, not legal advice: the owner has them checked by a lawyer before publishing.
"""
from __future__ import annotations

NOTE_RU = "Действующая редакция от {date}."
NOTE_TR = {"en": "Translation for convenience. In case of any discrepancy the Russian version prevails. Version of {date}.",
           "uk": "Переклад для зручності. У разі розбіжностей переважає російська редакція. Редакція від {date}."}

OFFER_RU = """## 1. Общие положения
- Настоящий документ — публичная оферта (ст. 435, п. 2 ст. 437 Гражданского кодекса РФ) {seller_genitive} (далее — Исполнитель) любому дееспособному лицу (далее — Пользователь) заключить договор оказания услуг на изложенных условиях.
- Акцептом оферты (п. 3 ст. 438 ГК РФ) считается оплата тарифа, активация пробного периода или подарочного кода. С момента акцепта договор считается заключённым.
- Сервис — «{brand}»: доступ к защищённому VPN-соединению через серверы Исполнителя, личный кабинет на {site}, Telegram-бот и мобильные приложения.

## 2. Предмет договора
- Исполнитель предоставляет Пользователю доступ к Сервису на срок и с ограничениями выбранного тарифа: число одновременно подключённых устройств, объём трафика, доступные локации.
- Актуальные тарифы и цены опубликованы в личном кабинете, Telegram-боте и приложениях. Цена фиксируется в момент оплаты и не меняется для оплаченного периода.
- Пробный период предоставляется один раз на одного Пользователя и одно устройство, на условиях, показанных при его активации.
- Услуга считается оказанной надлежащим образом, если доступ был предоставлен на оплаченный срок. Исполнитель не гарантирует доступность конкретных сайтов и сервисов третьих лиц и скорость, зависящую от сети Пользователя и провайдера связи.

## 3. Оплата
- Оплата производится банковской картой, через СБП, электронные кошельки, криптовалюту или с баланса личного кабинета — способами, доступными на странице оплаты. Платежи обрабатывают платёжные сервисы-партнёры; данные карт Исполнителю не передаются.
- Доступ предоставляется после подтверждения оплаты платёжным сервисом. Уведомление о платеже без такого подтверждения не является оплатой.
- Кассовый чек направляется в соответствии с Федеральным законом от 22.05.2003 № 54-ФЗ «О применении контрольно-кассовой техники» {receipt_line}.
- Промокоды, скидки и бонусные дни применяются по условиям, показанным при оплате, и не суммируются, если не указано иное.

## 4. Автопродление
- Пользователь может включить автопродление и сохранить способ оплаты. Тогда за несколько дней до окончания срока стоимость следующего периода списывается автоматически по цене, показанной в личном кабинете.
- Автопродление отключается в любой момент в личном кабинете или Telegram-боте; сохранённый способ оплаты можно удалить. Об успешном и неуспешном списании Пользователь получает уведомление.

## 5. Заморозка подписки
- Если Исполнитель включил эту возможность, Пользователь может приостановить оплаченную подписку на срок и в пределах лимитов, показанных в личном кабинете. На время заморозки доступ отключается, оплаченный срок продлевается на время заморозки.

## 6. Права и обязанности сторон
- Исполнитель обязуется предоставлять доступ к Сервису на оплаченный срок, обеспечивать работу поддержки и защищать персональные данные Пользователя согласно Политике конфиденциальности.
- Исполнитель вправе проводить технические работы, менять состав серверов и локаций без ухудшения условий оплаченного тарифа, а также приостановить доступ при нарушении Правил пользования Сервисом.
- Пользователь обязуется соблюдать законодательство Российской Федерации и Правила пользования Сервисом, не передавать доступ третьим лицам сверх лимита устройств тарифа и сохранять в тайне данные для входа.

## 7. Отказ от услуги и возврат денежных средств
- Пользователь вправе отказаться от договора в любое время (ст. 32 Закона РФ «О защите прав потребителей», ст. 782 ГК РФ) при условии оплаты Исполнителю фактически понесённых расходов.
- При отказе возвращается стоимость неиспользованной части оплаченного периода. Для возврата Пользователь обращается в поддержку: {email} или раздел «Поддержка» в личном кабинете и Telegram-боте.
- Возврат производится тем же способом, которым была произведена оплата, в срок до 10 дней с момента обращения (ст. 31 Закона «О защите прав потребителей»). Сроки зачисления зависят от банка и платёжного сервиса.
- Пробный период и подарочные бонусы денежной стоимости не имеют и не возвращаются.
- При блокировке доступа за нарушение Правил пользования возврат за неиспользованный период производится за вычетом фактических расходов Исполнителя, если иное не предусмотрено законом.

## 8. Ответственность
- Стороны несут ответственность в соответствии с законодательством РФ. Исполнитель не отвечает за действия Пользователя в сети Интернет при использовании Сервиса и за перерывы, вызванные действиями третьих лиц, в том числе операторов связи и органов власти, а также обстоятельствами непреодолимой силы.
- Совокупная ответственность Исполнителя ограничена стоимостью оплаченного периода, кроме случаев, когда такое ограничение не допускается законом.

## 9. Претензии и споры
- Претензии направляются на {email}. Срок ответа — 10 дней.
- Споры разрешаются в порядке, установленном законодательством РФ; потребитель вправе обратиться в суд по месту своего жительства.

## 10. Изменение оферты
- Исполнитель вправе изменять оферту, публикуя новую редакцию в личном кабинете и боте. Новая редакция применяется к оплатам, совершённым после её публикации.

## 11. Реквизиты Исполнителя
{requisites}"""

PRIVACY_RU = """## 1. Общие положения
- Политика определяет порядок обработки и защиты персональных данных пользователей сервиса «{brand}» в соответствии с Федеральным законом от 27.07.2006 № 152-ФЗ «О персональных данных».
- Оператор персональных данных — {seller_nominative}{rkn_line}. Контакт по вопросам персональных данных: {email}.
- Используя Сервис, Пользователь соглашается с Политикой. Согласие на обработку персональных данных даётся при регистрации и может быть отозвано (раздел 7).

## 2. Какие данные мы обрабатываем
- Учётные данные: адрес электронной почты, Telegram ID, имя пользователя и имя в Telegram; при входе через Яндекс ID, VK ID или Google — идентификатор и адрес почты, переданные этими сервисами с согласия Пользователя.
- Данные о подписке и устройствах: тариф, сроки, история оплат (сумма, способ, статус; данные банковских карт Исполнителю не передаются), идентификаторы подключённых устройств (HWID) для соблюдения лимита устройств.
- Технические данные: IP-адрес, страна и, если включено, регион по IP при подключении к серверам; время подключения; объём использованного трафика; сведения о качестве связи и скорости из приложений; если включена защита от торрентов — число таких соединений по часам (30 дней), без адресов и содержимого.
- Обращения в поддержку и их содержание, ответы на опросы и оценки.
- Cookie-файлы личного кабинета, необходимые для входа и защиты от подделки запросов.
- Содержимое интернет-трафика Пользователя, посещаемые сайты и DNS-запросы Исполнитель не записывает и не хранит.

## 3. Цели обработки
- Заключение и исполнение договора: регистрация, предоставление доступа, учёт срока и устройств, приём оплаты, выдача чеков.
- Поддержка Пользователя и уведомления о подписке, оплатах и работе Сервиса.
- Защита Сервиса от мошенничества, злоупотреблений и передачи доступа сверх лимита.
- Улучшение качества Сервиса по обобщённой статистике.
- Рассылки об акциях — только с отдельного согласия, от которого можно отказаться в любой момент.

## 4. Правовые основания
- Исполнение договора, стороной которого является Пользователь (п. 5 ч. 1 ст. 6 152-ФЗ), согласие Пользователя (п. 1 ч. 1 ст. 6), исполнение обязанностей, возложенных законом (налоговый и кассовый учёт).

## 5. Передача данных третьим лицам
- Данные передаются только в объёме, необходимом для оказания услуги: платёжным сервисам — для проведения оплаты и возвратов; оператору фискальных данных — для чеков; Telegram — для работы бота; почтовому сервису — для писем; сервисам уведомлений Google и Apple — для push-уведомлений; хостинг-провайдерам серверов.
- Серверы VPN могут находиться за пределами Российской Федерации. Трансграничная передача технических данных (IP-адрес, время подключения) осуществляется для исполнения договора в соответствии со ст. 12 152-ФЗ.
- Данные не продаются и не передаются для рекламы третьих лиц. Предоставление данных государственным органам — только в случаях и порядке, предусмотренных законом.

## 6. Сроки хранения
- Учётные данные и история оплат — в течение действия аккаунта и после его удаления в сроки, требуемые налоговым и бухгалтерским законодательством.
- Сведения о подключениях (IP-адрес, время) — не дольше {session_days} дней; замеры качества и скорости — 30 дней.
- Обращения в поддержку — до удаления аккаунта.

## 7. Права Пользователя
- Получать сведения об обработке своих данных, требовать их уточнения, блокирования или уничтожения, отозвать согласие (ст. 14, 21 152-ФЗ).
- Удалить аккаунт можно в личном кабинете или через поддержку. Запросы направляются на {email}; срок ответа — 10 рабочих дней (ч. 3 ст. 14 152-ФЗ).
- Пользователь вправе обжаловать действия оператора в Роскомнадзоре или в суде.

## 8. Защита данных
- Данные хранятся на защищённых серверах; секреты и платёжные ключи — в зашифрованном виде; доступ сотрудников ограничен ролями и записывается в журнал; соединения защищены TLS.

## 9. Изменение Политики
- Новая редакция публикуется в личном кабинете и боте и действует с момента публикации.

## 10. Контакты оператора
{requisites}"""

RULES_RU = """## 1. Общие положения
- Правила обязательны для всех пользователей сервиса «{brand}» и являются частью публичной оферты. Используя Сервис, Пользователь подтверждает согласие с Правилами.

## 2. Назначение Сервиса
- Сервис предназначен для защиты соединения и персональных данных при работе в сетях общего доступа, конфиденциальности и безопасного доступа к сети Интернет.
- Пользователь самостоятельно отвечает за соблюдение законодательства Российской Федерации, в том числе Федерального закона от 27.07.2006 № 149-ФЗ «Об информации, информационных технологиях и о защите информации», при использовании Сервиса.

## 3. Запрещается
- Использовать Сервис для действий, нарушающих законодательство РФ: распространения запрещённой информации, мошенничества, распространения вредоносных программ, доступа к чужим системам без разрешения, нарушения прав на результаты интеллектуальной деятельности.
- Рассылать спам, проводить атаки на сети и сервисы (в том числе DDoS), сканировать чужие сети.
- Передавать доступ третьим лицам сверх лимита устройств тарифа, перепродавать доступ без договора с Исполнителем.
- Вмешиваться в работу Сервиса, обходить ограничения тарифа, многократно получать пробный период.
- Создавать чрезмерную нагрузку, мешающую другим пользователям (например, массовые загрузки через торрент-сети, если это ограничено настройками Сервиса).

## 4. Меры при нарушении
- Исполнитель вправе предупредить Пользователя, ограничить скорость, отключить отдельные устройства или приостановить доступ до устранения нарушения.
- При грубом или повторном нарушении договор может быть расторгнут; возврат — по разделу 7 оферты.
- Исполнитель сотрудничает с уполномоченными органами в случаях и порядке, предусмотренных законом.

## 5. Устройства и учётная запись
- Число одновременно подключённых устройств ограничено тарифом. Устройства можно отключить в личном кабинете или боте.
- Пользователь отвечает за сохранность данных для входа и ссылки подписки. При утечке ссылки её можно сменить в личном кабинете.

## 6. Качество услуги
- Скорость и доступность зависят от сети Пользователя, провайдера связи и действий третьих лиц. Исполнитель проводит технические работы с предварительным уведомлением, когда это возможно; о сбоях сообщается на странице статуса и в боте.

## 7. Поддержка
- Поддержка — в разделе «Поддержка» личного кабинета и Telegram-бота, а также по адресу {email}.

## 8. Изменение Правил
- Новая редакция публикуется в личном кабинете и боте и действует с момента публикации."""

OFFER_EN = """## 1. General
- This document is a public offer by {seller_nominative} (the Provider) to any person with legal capacity (the User) to conclude a service agreement under Articles 435 and 437 of the Civil Code of the Russian Federation.
- The offer is accepted by paying for a plan, activating the trial or a gift code; the agreement is concluded from that moment.
- The Service is «{brand}»: access to a protected VPN connection through the Provider's servers, the personal cabinet at {site}, the Telegram bot and the mobile apps.

## 2. Subject
- The Provider gives the User access to the Service for the term and within the limits of the chosen plan: devices connected at once, traffic, locations.
- Current plans and prices are published in the cabinet, the bot and the apps. The price is fixed at payment for the paid period.
- The trial is given once per User and device on the terms shown at activation.
- The service is rendered when access was provided for the paid term. The Provider does not guarantee access to particular third-party sites or speed that depends on the User's network and carrier.

## 3. Payment
- Payment is made by the methods shown on the payment page; payments are processed by partner payment services, card data is not passed to the Provider.
- Access is given after the payment service confirms the payment. A payment notice without that confirmation is not a payment.
- Receipts are issued under Federal Law No. 54-FZ {receipt_line}.

## 4. Auto-renewal
- With auto-renewal on, the next period is charged a few days before the end at the price shown in the cabinet. It can be switched off at any time in the cabinet or the bot, and the saved payment method can be removed.

## 5. Pausing the subscription
- Where the Provider has enabled it, the User may pause a paid subscription within the limits shown in the cabinet; access is off for that time and the paid term moves by the same time.

## 6. Rights and obligations
- The Provider gives access for the paid term, runs support and protects personal data under the Privacy Policy; may carry out maintenance, change servers and locations without worsening the paid plan, and suspend access for breach of the Terms of Use.
- The User complies with the law and the Terms of Use, does not share access beyond the plan's device limit and keeps login data secret.

## 7. Cancellation and refunds
- The User may withdraw at any time, paying the Provider's actual expenses (Article 32 of the Russian Consumer Protection Law). The unused part of the paid period is refunded on request to {email} or through «Support», by the original payment method, within 10 days of the request.
- The trial and gift bonuses have no monetary value and are not refunded.

## 8. Liability
- The parties are liable under Russian law. The Provider is not liable for the User's actions on the Internet or for interruptions caused by third parties or force majeure. Its total liability is limited to the price of the paid period unless the law forbids such a limit.

## 9. Claims and disputes
- Claims are sent to {email}; the answer is given within 10 days. Disputes are resolved under Russian law.

## 10. Changes
- A new version is published in the cabinet and the bot and applies to payments made after publication.

## 11. Provider details
{requisites}"""

PRIVACY_EN = """## 1. General
- This policy sets out how personal data of the users of «{brand}» is processed and protected under Russian Federal Law No. 152-FZ «On Personal Data».
- The operator is {seller_nominative}{rkn_line}. Contact for personal data questions: {email}.

## 2. Data we process
- Account data: e-mail, Telegram ID, username and name; with Yandex ID, VK ID or Google sign-in — the identifier and e-mail those services pass with the User's consent.
- Subscription and device data: plan, terms, payment history (amount, method, status; card data is not passed to the Provider), device identifiers (HWID) for the device limit.
- Technical data: IP address, country and, where enabled, region by IP when connecting to the servers; connection time; traffic used; connection quality and speed measurements from the apps; where torrent protection is on — hourly counts of such connections (30 days), without addresses or content.
- Support requests, survey answers and ratings; cabinet cookies needed for sign-in and request forgery protection.
- The content of the User's traffic, the sites visited and DNS queries are not recorded or stored.

## 3. Purposes and legal grounds
- Performing the agreement (registration, access, devices, payments, receipts), support and service notices, protection against fraud and abuse, aggregated statistics; marketing messages only with separate consent. Grounds: performance of the agreement, consent, legal obligations.

## 4. Sharing
- Only as needed to render the service: payment services, the fiscal data operator, Telegram, the e-mail service, Google and Apple push services, server hosting. VPN servers may be outside Russia; technical data (IP address, connection time) is transferred abroad to perform the agreement. Data is not sold.

## 5. Retention
- Account data and payment history — while the account exists and afterwards as tax and accounting law requires. Connection records (IP address, time) — no longer than {session_days} days; quality and speed measurements — 30 days. Support requests — until the account is deleted.

## 6. User rights
- To get information on processing, to have data corrected, blocked or destroyed, to withdraw consent; to delete the account in the cabinet or through support. Requests to {email}; the answer within 10 working days. Complaints may be filed with Roskomnadzor or a court.

## 7. Security
- Data is kept on protected servers, secrets and payment keys encrypted, staff access limited by roles and logged, connections protected by TLS.

## 8. Operator contacts
{requisites}"""

RULES_EN = """## 1. General
- These Terms are binding on all users of «{brand}» and are part of the public offer.

## 2. Purpose of the Service
- The Service protects the connection and personal data on public networks and gives private, secure access to the Internet. The User is responsible for complying with the law, including Russian Federal Law No. 149-FZ «On Information», when using it.

## 3. Prohibited
- Unlawful actions: spreading prohibited information, fraud, malware, unauthorised access to systems, infringement of intellectual property rights.
- Spam, attacks on networks and services (including DDoS), scanning other networks.
- Sharing access beyond the plan's device limit, reselling access without an agreement with the Provider.
- Interfering with the Service, bypassing plan limits, taking the trial repeatedly.
- Excessive load that harms other users.

## 4. Measures
- The Provider may warn the User, limit speed, disconnect devices or suspend access until the breach ends; a serious or repeated breach ends the agreement, refunds under section 7 of the offer.

## 5. Devices and account
- The number of devices connected at once is limited by the plan; devices can be disconnected in the cabinet or the bot. The User keeps login data and the subscription link safe; a leaked link can be changed in the cabinet.

## 6. Quality and support
- Speed and availability depend on the User's network, the carrier and third parties; outages are reported on the status page and in the bot. Support — «Support» in the cabinet and the bot, or {email}.

## 7. Changes
- A new version is published in the cabinet and the bot and applies from publication."""

OFFER_UK = """## 1. Загальні положення
- Цей документ — публічна оферта (ст. 435, 437 Цивільного кодексу РФ) {seller_genitive} (далі — Виконавець) будь-якій дієздатній особі (далі — Користувач) укласти договір надання послуг на викладених умовах.
- Акцептом є оплата тарифу, активація пробного періоду або подарункового коду; з цього моменту договір укладено.
- Сервіс — «{brand}»: доступ до захищеного VPN-з'єднання через сервери Виконавця, особистий кабінет на {site}, Telegram-бот і мобільні застосунки.

## 2. Предмет договору
- Виконавець надає доступ до Сервісу на строк і в межах обраного тарифу: кількість одночасно підключених пристроїв, трафік, локації. Чинні тарифи й ціни опубліковані в кабінеті, боті та застосунках; ціна фіксується в момент оплати.
- Пробний період надається один раз на Користувача й пристрій.
- Виконавець не гарантує доступність окремих сайтів третіх осіб і швидкість, що залежить від мережі Користувача.

## 3. Оплата
- Оплата — способами зі сторінки оплати через платіжні сервіси-партнери; дані карток Виконавцю не передаються. Доступ надається після підтвердження оплати платіжним сервісом. Чек — відповідно до Закону РФ № 54-ФЗ {receipt_line}.

## 4. Автопродовження
- Наступний період списується за кілька днів до кінця строку за ціною з кабінету. Автопродовження вимикається будь-коли в кабінеті або боті.

## 5. Заморожування підписки
- Якщо Виконавець увімкнув цю можливість, Користувач може призупинити оплачену підписку в межах лімітів кабінету; оплачений строк зсувається на час заморожування.

## 6. Права та обов'язки
- Виконавець надає доступ на оплачений строк, підтримку й захист персональних даних; може проводити технічні роботи та призупинити доступ у разі порушення Правил.
- Користувач дотримується закону й Правил, не передає доступ понад ліміт пристроїв.

## 7. Відмова та повернення коштів
- Користувач може відмовитися від договору будь-коли, оплативши фактичні витрати Виконавця (ст. 32 Закону РФ «Про захист прав споживачів»). Вартість невикористаної частини періоду повертається за зверненням на {email} або через «Підтримку» тим самим способом оплати протягом 10 днів.
- Пробний період і подарункові бонуси не повертаються.

## 8. Відповідальність, спори, зміни
- Сторони відповідають за законодавством РФ; відповідальність Виконавця обмежена вартістю оплаченого періоду, якщо закон не забороняє такого обмеження. Претензії — на {email}, відповідь протягом 10 днів. Нова редакція публікується в кабінеті й боті.

## 9. Реквізити Виконавця
{requisites}"""

PRIVACY_UK = """## 1. Загальні положення
- Політика визначає обробку й захист персональних даних користувачів «{brand}» відповідно до Закону РФ № 152-ФЗ «Про персональні дані». Оператор — {seller_nominative}{rkn_line}. Контакт: {email}.

## 2. Які дані обробляються
- Облікові: e-mail, Telegram ID, ім'я користувача та ім'я; при вході через Яндекс ID, VK ID або Google — ідентифікатор і e-mail, передані цими сервісами за згодою Користувача.
- Підписка й пристрої: тариф, строки, історія оплат (дані карток не передаються), ідентифікатори пристроїв (HWID).
- Технічні: IP-адреса, країна й, якщо увімкнено, регіон за IP під час підключення; час підключення; обсяг трафіку; заміри якості та швидкості із застосунків; якщо увімкнено захист від торентів — кількість таких з'єднань за годинами (30 днів), без адрес і вмісту.
- Звернення до підтримки, відповіді на опитування, cookie кабінету для входу.
- Вміст трафіку, відвідані сайти й DNS-запити не записуються й не зберігаються.

## 3. Цілі та підстави
- Виконання договору, підтримка й повідомлення, захист від шахрайства, узагальнена статистика; розсилки — лише за окремою згодою.

## 4. Передача
- Лише в потрібному обсязі: платіжним сервісам, оператору фіскальних даних, Telegram, поштовому сервісу, сервісам push Google і Apple, хостингу серверів. Сервери VPN можуть бути за межами РФ. Дані не продаються.

## 5. Строки зберігання
- Облікові дані й оплати — поки існує акаунт і далі за вимогами податкового законодавства; підключення (IP, час) — не довше {session_days} днів; заміри якості — 30 днів.

## 6. Права Користувача
- Отримувати відомості про обробку, вимагати уточнення, блокування або знищення даних, відкликати згоду, видалити акаунт. Запити — на {email}, відповідь протягом 10 робочих днів.

## 7. Контакти оператора
{requisites}"""

RULES_UK = """## 1. Загальні положення
- Правила обов'язкові для всіх користувачів «{brand}» і є частиною публічної оферти.

## 2. Призначення Сервісу
- Сервіс захищає з'єднання й персональні дані в мережах загального доступу. Користувач сам відповідає за дотримання законодавства, зокрема Закону РФ № 149-ФЗ «Про інформацію», під час використання Сервісу.

## 3. Заборонено
- Незаконні дії: поширення забороненої інформації, шахрайство, шкідливі програми, несанкціонований доступ, порушення прав інтелектуальної власності.
- Спам, атаки на мережі (зокрема DDoS), сканування чужих мереж.
- Передача доступу понад ліміт пристроїв, перепродаж без договору з Виконавцем, обхід обмежень тарифу, повторне отримання пробного періоду.

## 4. Заходи
- Попередження, обмеження швидкості, відключення пристроїв або призупинення доступу; за грубе чи повторне порушення — розірвання договору, повернення за розділом 7 оферти.

## 5. Пристрої, якість, підтримка
- Кількість пристроїв обмежена тарифом. Швидкість залежить від мережі Користувача й третіх осіб. Підтримка — «Підтримка» в кабінеті й боті або {email}.

## 6. Зміни
- Нова редакція публікується в кабінеті й боті."""

TEMPLATES = {
    "ru": {"offer": OFFER_RU, "privacy": PRIVACY_RU, "rules": RULES_RU},
    "en": {"offer": OFFER_EN, "privacy": PRIVACY_EN, "rules": RULES_EN},
    "uk": {"offer": OFFER_UK, "privacy": PRIVACY_UK, "rules": RULES_UK},
}
