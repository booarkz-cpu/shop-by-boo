"""SelfSteal sites (v28.91.0, stage 20, N8): what a stranger sees on a node's domain.

Two sources, both turned into the same «bundle» — a dict ``{relative path: bytes}`` that the installer packs into a
tar.gz and unpacks into the node's ``/opt/remnawave-selfsteal/site`` (rw_steps.SITE):

* the catalogue — 22 templates written for the shop (texts, colours and pictures of our own, no outside requests). Each
  node gets its own build: the name, palette, layout, order of sections and the pictures follow from a hash of the
  domain, so two nodes on one template do not look the same. Every build has inner pages, a 404 page, robots.txt with
  the sitemap — what the outside check (selfsteal_check) looks for;
* an archive the administrator uploads (zip or tar.gz): checked file by file — only static web files, no hidden or
  service files, no server scripts, no links, no paths outside the site; index.html with a <title> in the root or in
  the only folder; 20 MB at most.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import io
import posixpath
import re
import tarfile
import zipfile
from dataclasses import dataclass

THEMES = {
    "creative": ("Творчество и дизайн", "Creative & design"),
    "tech": ("Технологии", "Technology"),
    "business": ("Бизнес и услуги", "Business & services"),
    "education": ("Образование", "Education"),
    "food": ("Еда и дом", "Food & home"),
    "travel": ("Путешествия", "Travel"),
    "hobby": ("Хобби", "Hobbies"),
}
LANGS = ("ru", "en")


@dataclass(frozen=True)
class Template:
    id: str
    theme: str
    hues: tuple[int, int, int]           # three base hues; the node's build takes one and shifts it a little
    section: tuple[str, str]             # the inner list page: (slug, «ru title|en title»)
    ru: tuple[tuple[str, ...], str, tuple[str, str, str], str]  # names, tagline, three items, about
    en: tuple[tuple[str, ...], str, tuple[str, str, str], str]

    def title(self, lang: str) -> str:
        return (self.ru if lang == "ru" else self.en)[0][0]


T = Template
CATALOGUE: tuple[Template, ...] = (
    T("cloud", "tech", (217, 199, 230), ("files", "Тарифы|Plans"),
      (("Облако Сота", "Пчела Диск", "Ясная полка"), "Синхронизация и резервные копии для небольших команд",
       ("Шифрование на устройстве", "Версии файлов за 30 дней", "Доступ по ссылке с паролем"),
       "Мы храним файлы в двух дата-центрах и ничего не показываем рекламодателям."),
      (("Honeycomb Cloud", "Shelfbox", "Clearvault"), "Sync and backups for small teams",
       ("On-device encryption", "30 days of file versions", "Password-protected links"),
       "Files live in two data centres and are never shown to advertisers.")),
    T("docs", "tech", (172, 160, 190), ("guides", "Руководства|Guides"),
      (("Справочник Тропа", "Док-станция", "Ясный мануал"), "Руководства, справочник API и заметки к выпускам",
       ("Быстрый старт за 10 минут", "Справочник API", "Заметки к выпускам"),
       "Документация пишется вместе с кодом и обновляется с каждым выпуском."),
      (("Trailhead Docs", "Dockside Manual", "Plainguide"), "Guides, API reference and release notes",
       ("Ten-minute quick start", "API reference", "Release notes"),
       "The documentation is written with the code and updated with every release.")),
    T("corgi", "hobby", (24, 32, 14), ("posts", "Записи|Posts"),
      (("Дневник корги", "Лапы и хвост", "Короткие лапки"), "Прогулки, рецепты лакомств и советы по уходу",
       ("Осенние прогулки", "Печенье из тыквы", "Как вычёсывать подшёрсток"),
       "Блог о жизни с двумя корги в маленьком городе."),
      (("Corgi Diary", "Paws and Tail", "Short Legs Club"), "Walks, treat recipes and grooming tips",
       ("Autumn walks", "Pumpkin dog biscuits", "Brushing the undercoat"),
       "A blog about life with two corgis in a small town.")),
    T("photo", "creative", (330, 280, 0), ("works", "Работы|Work"),
      (("Студия Свет", "Кадр и тень", "Мягкий фокус"), "Портреты, свадьбы и предметная съёмка",
       ("Семейные портреты", "Съёмка для каталогов", "Печать на хлопковой бумаге"),
       "Снимаем при естественном свете и печатаем работы в своей мастерской."),
      (("Lightroom Studio", "Frame & Shade", "Soft Focus"), "Portraits, weddings and product photography",
       ("Family portraits", "Catalogue photography", "Prints on cotton paper"),
       "We shoot in natural light and print our work in our own studio.")),
    T("design", "creative", (262, 300, 190), ("projects", "Проекты|Projects"),
      (("Бюро Линия", "Сетка и цвет", "Плоскость"), "Айдентика, сайты и упаковка для малого бизнеса",
       ("Логотип и фирменный стиль", "Сайт на конструкторе", "Упаковка и этикетки"),
       "Небольшое бюро: три дизайнера и один кот, работаем с 2019 года."),
      (("Line Bureau", "Grid & Colour", "Flatland"), "Identity, websites and packaging for small businesses",
       ("Logo and brand style", "Website builds", "Packaging and labels"),
       "A small studio of three designers and a cat, working since 2019.")),
    T("ceramics", "creative", (18, 35, 160), ("classes", "Занятия|Classes"),
      (("Глина и печь", "Мастерская Круг", "Тёплая керамика"), "Гончарная мастерская и посуда ручной работы",
       ("Пробное занятие на круге", "Курс для начинающих", "Посуда на заказ"),
       "Обжигаем в электрической печи, глазури готовим сами."),
      (("Clay & Kiln", "Wheel Workshop", "Warm Ceramics"), "A pottery workshop and handmade tableware",
       ("Trial wheel lesson", "Beginners' course", "Tableware to order"),
       "We fire in an electric kiln and mix our own glazes.")),
    T("music", "creative", (280, 45, 205), ("lessons", "Уроки|Lessons"),
      (("Нота Плюс", "Школа Камертон", "Тихий аккорд"), "Уроки гитары, фортепиано и вокала для взрослых",
       ("Гитара с нуля", "Фортепиано по нотам", "Постановка голоса"),
       "Занимаемся вживую и онлайн, первый урок бесплатный."),
      (("Note Plus", "Tuning Fork School", "Quiet Chord"), "Guitar, piano and voice lessons for adults",
       ("Guitar from scratch", "Piano reading", "Voice training"),
       "Lessons in person and online; the first one is free.")),
    T("bakery", "food", (30, 12, 45), ("menu", "Меню|Menu"),
      (("Пекарня Колос", "Тёплый хлеб", "Корочка"), "Хлеб на закваске и выпечка каждое утро",
       ("Ржаной на закваске", "Круассаны по выходным", "Торты на заказ"),
       "Печём с шести утра из муки местных мельниц."),
      (("Ear of Wheat Bakery", "Warm Loaf", "The Crust"), "Sourdough bread and pastries every morning",
       ("Rye sourdough", "Weekend croissants", "Cakes to order"),
       "We bake from six in the morning with flour from local mills.")),
    T("coffee", "food", (25, 15, 120), ("beans", "Зерно|Beans"),
      (("Обжарка Утро", "Зёрна и пар", "Кофейная лавка"), "Обжариваем зерно небольшими партиями",
       ("Эфиопия, мытая обработка", "Бразилия для эспрессо", "Подписка на зерно"),
       "Обжарка раз в неделю, отправка в день обжарки."),
      (("Morning Roast", "Beans & Steam", "The Coffee Stall"), "Small-batch coffee roasting",
       ("Ethiopia, washed", "Brazil for espresso", "Bean subscription"),
       "We roast once a week and ship on roasting day.")),
    T("recipes", "food", (95, 10, 50), ("recipes", "Рецепты|Recipes"),
      (("Кухня на выходных", "Ложка мёда", "Простые обеды"), "Домашние рецепты на каждый день",
       ("Суп из запечённой тыквы", "Пирог с яблоками", "Овощи на гриле"),
       "Проверяем каждый рецепт трижды перед публикацией."),
      (("Weekend Kitchen", "Spoon of Honey", "Simple Lunches"), "Home recipes for every day",
       ("Roast pumpkin soup", "Apple pie", "Grilled vegetables"),
       "Every recipe is cooked three times before it is published.")),
    T("travel", "travel", (195, 210, 25), ("notes", "Заметки|Notes"),
      (("Карта и рюкзак", "Дальние берега", "Путевые листы"), "Заметки о маршрутах по России и соседним странам",
       ("Байкал зимой", "Неделя на Алтае", "Города Золотого кольца"),
       "Путешествуем на поездах и пишем, сколько всё стоило."),
      (("Map & Backpack", "Far Shores", "Travel Sheets"), "Route notes from the road",
       ("Lake Baikal in winter", "A week in the Altai", "Old towns by train"),
       "We travel by train and write down what everything cost.")),
    T("guesthouse", "travel", (150, 35, 205), ("rooms", "Номера|Rooms"),
      (("Гостевой дом Сосны", "У озера", "Тихая улица"), "Небольшой гостевой дом у леса",
       ("Номер с видом на лес", "Семейный номер", "Завтраки из местных продуктов"),
       "Шесть номеров, сауна и прокат велосипедов."),
      (("Pines Guest House", "By the Lake", "Quiet Street Inn"), "A small guest house by the forest",
       ("Forest view room", "Family room", "Local breakfasts"),
       "Six rooms, a sauna and bikes to rent.")),
    T("hiking", "travel", (110, 140, 35), ("trails", "Маршруты|Trails"),
      (("Тропы выходного дня", "Перевал", "Шаг за шагом"), "Пешие маршруты с картами и описанием",
       ("Кольцо вокруг озера, 12 км", "Подъём на хребет", "Маршрут для детей"),
       "Каждый маршрут пройден нами, треки обновляем весной."),
      (("Weekend Trails", "The Pass", "Step by Step"), "Hiking routes with maps and notes",
       ("Lake loop, 12 km", "Ridge climb", "Family-friendly route"),
       "We walked every route ourselves and update the tracks each spring.")),
    T("languages", "education", (220, 350, 160), ("courses", "Курсы|Courses"),
      (("Языковая студия Слово", "Разговорный клуб", "Лингва"), "Английский и испанский в мини-группах",
       ("Разговорный английский", "Испанский для поездок", "Подготовка к экзаменам"),
       "Группы до шести человек, занятия по вечерам."),
      (("Word Language Studio", "Conversation Club", "Lingua"), "English and Spanish in small groups",
       ("Conversational English", "Spanish for travel", "Exam preparation"),
       "Groups of up to six, evening classes.")),
    T("tutoring", "education", (240, 200, 280), ("subjects", "Предметы|Subjects"),
      (("Математика без страха", "Репетитор рядом", "Задачник"), "Занятия по математике и физике для школьников",
       ("Алгебра 7–9 класс", "Подготовка к олимпиадам", "Физика с опытами"),
       "Объясняем на примерах и даём домашние задания с разбором."),
      (("Maths Without Fear", "Tutor Next Door", "Problem Book"), "Maths and physics lessons for school students",
       ("Algebra basics", "Olympiad preparation", "Physics with experiments"),
       "We explain with examples and review every homework.")),
    T("bookclub", "education", (5, 40, 190), ("books", "Книги|Books"),
      (("Книжный клуб Полка", "Читаем вместе", "Закладка"), "Встречи читателей раз в две недели",
       ("Книга месяца", "Обмен книгами", "Встречи с авторами"),
       "Собираемся в городской библиотеке, вход свободный."),
      (("Shelf Book Club", "Reading Together", "Bookmark"), "Readers meet every other week",
       ("Book of the month", "Book swap", "Author evenings"),
       "We meet at the city library; entry is free.")),
    T("accounting", "business", (210, 140, 230), ("services", "Услуги|Services"),
      (("Бухгалтерия Баланс", "Счёт и учёт", "Ясные цифры"), "Бухгалтерия и отчётность для ИП и ООО",
       ("Ведение учёта", "Отчётность и налоги", "Консультации по договорам"),
       "Работаем с 2015 года, отвечаем в течение рабочего дня."),
      (("Balance Accounting", "Ledger & Co", "Clear Numbers"), "Bookkeeping and reporting for small companies",
       ("Bookkeeping", "Reports and taxes", "Contract advice"),
       "Working since 2015; we answer within a working day.")),
    T("delivery", "business", (35, 200, 0), ("services", "Услуги|Services"),
      (("Курьер Пчела", "Быстрая доставка", "Точно в срок"), "Доставка документов и посылок по городу",
       ("Доставка за два часа", "Забор с адреса", "Отслеживание по номеру"),
       "Курьеры на велосипедах и электромобилях."),
      (("Bee Courier", "Swift Delivery", "On Time"), "Documents and parcels across the city",
       ("Two-hour delivery", "Pick-up from your door", "Tracking by number"),
       "Couriers on bicycles and electric cars.")),
    T("coworking", "business", (170, 260, 45), ("spaces", "Пространства|Spaces"),
      (("Коворкинг Улей", "Рабочее место", "Общий стол"), "Рабочие места и переговорные в центре города",
       ("Фиксированное место", "Переговорная на час", "Абонемент на 10 дней"),
       "Открыто с восьми до десяти, есть кухня и тихая комната."),
      (("Hive Coworking", "The Desk", "Common Table"), "Desks and meeting rooms in the city centre",
       ("Fixed desk", "Meeting room by the hour", "Ten-day pass"),
       "Open eight to ten, with a kitchen and a quiet room.")),
    T("devtools", "tech", (265, 190, 140), ("changelog", "Изменения|Changelog"),
      (("Сборщик Пульс", "Конвейер", "Тестовый стенд"), "Сервис сборки и проверки кода для команд",
       ("Сборки по каждому коммиту", "Отчёты о покрытии", "Кэш зависимостей"),
       "Работает в облаке и на своих серверах."),
      (("Pulse Build", "Pipeline", "Test Bench"), "Build and test service for teams",
       ("A build for every commit", "Coverage reports", "Dependency cache"),
       "Runs in the cloud or on your own servers.")),
    T("garden", "hobby", (120, 90, 340), ("articles", "Статьи|Articles"),
      (("Сад на балконе", "Грядка", "Зелёный уголок"), "Советы по саду, огороду и комнатным растениям",
       ("Томаты на балконе", "Как укрыть розы на зиму", "Пересадка монстеры"),
       "Пишем о том, что выросло у нас самих."),
      (("Balcony Garden", "The Bed", "Green Corner"), "Tips for gardens, vegetables and house plants",
       ("Balcony tomatoes", "Protecting roses for winter", "Repotting a monstera"),
       "We write about what grew in our own garden.")),
    T("bikes", "hobby", (0, 200, 45), ("services", "Услуги|Services"),
      (("Веломастерская Спица", "Цепь и звезда", "Педаль"), "Ремонт и обслуживание велосипедов",
       ("Сезонное обслуживание", "Настройка переключателей", "Сборка колёс"),
       "Мастерская в гараже у парка, запчасти в наличии."),
      (("Spoke Bike Shop", "Chain & Cog", "Pedal"), "Bicycle repair and servicing",
       ("Seasonal service", "Gear tuning", "Wheel building"),
       "A workshop in a garage by the park; parts in stock.")),
)
TEMPLATES = {t.id: t for t in CATALOGUE}
LAYOUTS = ("hero", "centered", "sidebar")


def catalogue() -> list[dict]:
    """What the admin panel lists: id, title, theme and the languages of every template."""
    return [{"id": t.id, "title": t.ru[0][0], "title_en": t.en[0][0], "theme": t.theme, "theme_title": THEMES[t.theme][0],
             "tagline": t.ru[1], "langs": list(LANGS)} for t in CATALOGUE]


def _seed(domain: str, template: str) -> bytes:
    return hashlib.sha256(f"{template}|{domain}".encode()).digest()


def variant(domain: str, template: str) -> dict:
    """The node's own build: the name, colour, layout and order of items follow from the domain."""
    t = TEMPLATES[template]
    s = _seed(domain, template)
    hue = (t.hues[s[0] % 3] + (s[1] % 21) - 10) % 360
    order = sorted(range(3), key=lambda i: s[2 + i])
    return {"name_index": s[5] % 3, "hue": hue, "layout": LAYOUTS[s[6] % 3], "order": order, "year": 2015 + s[7] % 9,
            "pattern": s[8] % 3}


def _hero_svg(hue: int, seed: bytes, pattern: int) -> str:
    """A picture of our own for the page: circles, stripes or waves in the build's colours."""
    shapes = []
    for i in range(9):
        x, y, r = seed[9 + i] * 3 % 800, seed[18 + i] % 300, 20 + seed[i] % 90
        light = 45 + (seed[i] % 35)
        if pattern == 0:
            shapes.append(f"<circle cx='{x}' cy='{y}' r='{r}' fill='hsl({(hue + i * 12) % 360},70%,{light}%)' opacity='.55'/>")
        elif pattern == 1:
            shapes.append(f"<rect x='{x}' y='-20' width='{r // 2 + 10}' height='360' transform='rotate(20 {x} 150)' "
                          f"fill='hsl({(hue + i * 9) % 360},65%,{light}%)' opacity='.45'/>")
        else:
            shapes.append(f"<path d='M0 {y} Q 200 {y - r} 400 {y} T 800 {y} V 300 H 0 Z' fill='hsl({(hue + i * 7) % 360},60%,{light}%)' "
                          "opacity='.25'/>")
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 300'><rect width='800' height='300' "
            f"fill='hsl({hue},55%,22%)'/>{''.join(shapes)}</svg>")


def _favicon(hue: int, letter: str) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='hsl({hue},65%,45%)'/>"
            f"<text x='32' y='43' font-size='34' text-anchor='middle' fill='#fff' font-family='sans-serif'>{html.escape(letter)}</text></svg>")


def _css(hue: int, layout: str) -> str:
    main = {"hero": "max-width:880px;margin:0 auto", "centered": "max-width:720px;margin:0 auto;text-align:center",
            "sidebar": "max-width:1000px;margin:0 auto;display:grid;grid-template-columns:220px 1fr;gap:32px"}[layout]
    return (":root{--a:hsl(%d,65%%,42%%);--b:hsl(%d,55%%,96%%);--t:#1f2328;--m:#5b6470}" % (hue, hue)
            + "*{box-sizing:border-box}body{margin:0;font:16px/1.65 system-ui,-apple-system,'Segoe UI',sans-serif;color:var(--t);background:var(--b)}"
            + "a{color:var(--a)}header{background:#fff;border-bottom:1px solid #e3e6ea}nav{max-width:1000px;margin:0 auto;padding:14px 20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}"
            + "nav .brand{font-weight:800;color:var(--t);text-decoration:none;margin-right:auto}nav a{text-decoration:none}"
            + ".hero img{width:100%;height:auto;display:block}main{" + main + ";padding:28px 20px}"
            + "h1{font-size:2rem;line-height:1.2;margin:.2em 0}.lead{color:var(--m);font-size:1.15rem}"
            + ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:24px 0}"
            + ".card{background:#fff;border:1px solid #e3e6ea;border-radius:14px;padding:18px}.card h3{margin:.2em 0}"
            + "aside{border-right:1px solid #e3e6ea;padding-right:16px}footer{color:var(--m);text-align:center;padding:28px 20px;font-size:.9rem}"
            + "@media(max-width:720px){main{display:block}aside{border:0}}")


def build_site(template: str, domain: str, lang: str = "ru") -> dict[str, bytes]:
    """The node's site from the catalogue: index, about, the list page, contacts, 404, robots.txt, sitemap.xml."""
    if template not in TEMPLATES:
        raise ValueError("Нет такого шаблона")
    if lang not in LANGS:
        raise ValueError("Язык сайта: ru или en")
    t, v, s = TEMPLATES[template], variant(domain, template), _seed(domain, template)
    names, tagline, items, about = t.ru if lang == "ru" else t.en
    name = names[v["name_index"]]
    items = [items[i] for i in v["order"]]
    slug, section_titles = t.section
    section = section_titles.split("|")[0 if lang == "ru" else 1]
    words = {"ru": {"home": "Главная", "about": "О нас", "contacts": "Контакты", "more": "Подробнее", "write": "Напишите нам",
                    "since": "с", "notfound": "Страница не найдена", "back": "Вернуться на главную",
                    "hours": "Отвечаем по будням с 10 до 19."},
             "en": {"home": "Home", "about": "About", "contacts": "Contacts", "more": "Read more", "write": "Write to us",
                    "since": "since", "notfound": "Page not found", "back": "Back to the home page",
                    "hours": "We answer on weekdays, 10 am to 7 pm."}}[lang]
    e = html.escape
    d = e(domain)
    links = [("/", words["home"]), (f"/{slug}/", section), ("/about/", words["about"]), ("/contacts/", words["contacts"])]

    # Pages: the body sits in <main>; the home page has the picture over it.
    def wrap(title: str, inner: str, path: str, hero: bool = False) -> bytes:
        nav = "".join(f"<a href='{href}'{' aria-current=page' if href == path else ''}>{e(label)}</a>" for href, label in links)
        side = f"<aside><p><b>{e(name)}</b></p><p>{e(tagline)}</p></aside>" if v["layout"] == "sidebar" else ""
        picture = "<div class='hero'><img src='/hero.svg' alt=''></div>" if hero else ""
        return (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                f"<title>{e(title)}</title><meta name='description' content='{e(tagline)}'><link rel='icon' href='/favicon.svg' type='image/svg+xml'>"
                f"<link rel='stylesheet' href='/style.css'></head><body><header><nav><a class='brand' href='/'>{e(name)}</a>{nav}</nav></header>"
                f"{picture}<main>{side}<div>{inner}</div></main><footer>© {v['year']}–2026 {e(name)} · {d}</footer></body></html>").encode()

    cards = "".join(f"<div class='card'><h3>{e(x)}</h3><p><a href='/{slug}/{i + 1}/'>{e(words['more'])}</a></p></div>" for i, x in enumerate(items))
    files: dict[str, bytes] = {
        "index.html": wrap(f"{name} — {tagline}", f"<h1>{e(name)}</h1><p class='lead'>{e(tagline)}</p><div class='cards'>{cards}</div>"
                                                   f"<p>{e(about)}</p>", "/", hero=True),
        "about/index.html": wrap(f"{words['about']} — {name}", f"<h1>{e(words['about'])}</h1><p>{e(about)}</p>"
                                                                 f"<p>{e(name)} — {e(tagline.lower())}, {words['since']} {v['year']}.</p>", "/about/"),
        f"{slug}/index.html": wrap(f"{section} — {name}", f"<h1>{e(section)}</h1><ul>"
                                   + "".join(f"<li><a href='/{slug}/{i + 1}/'>{e(x)}</a></li>" for i, x in enumerate(items)) + "</ul>",
                                   f"/{slug}/"),
        "contacts/index.html": wrap(f"{words['contacts']} — {name}", f"<h1>{e(words['contacts'])}</h1><p>{e(words['write'])}: "
                                    f"<a href='mailto:hello@{d}'>hello@{d}</a></p><p>{e(words['hours'])}</p>", "/contacts/"),
        "404.html": wrap(f"{words['notfound']} — {name}", f"<h1>404</h1><p>{e(words['notfound'])}.</p><p><a href='/'>{e(words['back'])}</a></p>",
                         "/404"),
        "style.css": _css(v["hue"], v["layout"]).encode(),
        "favicon.svg": _favicon(v["hue"], name[0]).encode(),
        "hero.svg": _hero_svg(v["hue"], s, v["pattern"]).encode(),
    }
    for i, x in enumerate(items):
        files[f"{slug}/{i + 1}/index.html"] = wrap(f"{x} — {name}", f"<h1>{e(x)}</h1><p class='lead'>{e(tagline)}</p><p>{e(about)}</p>"
                                                   f"<p><a href='/{slug}/'>{e(section)}</a></p>", f"/{slug}/")
    paths = ["/", "/about/", f"/{slug}/", "/contacts/"] + [f"/{slug}/{i + 1}/" for i in range(3)]
    files["sitemap.xml"] = ("<?xml version='1.0' encoding='UTF-8'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                            + "".join(f"<url><loc>https://{d}{p}</loc></url>" for p in paths) + "</urlset>").encode()
    files["robots.txt"] = f"User-agent: *\nAllow: /\nSitemap: https://{domain}/sitemap.xml\n".encode()
    return files


# ---------------------------------------------------------------- an uploaded archive

MAX_ARCHIVE = 20 * 1024 * 1024
MAX_UNPACKED = 60 * 1024 * 1024
MAX_FILES = 800
ALLOWED = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".txt", ".xml", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp",
           ".avif", ".ico", ".bmp", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".webm", ".ogg", ".mp3", ".wav", ".m4a",
           ".pdf", ".webmanifest", ".map", ".csv", ".md"}
SERVICE = {"__macosx", "thumbs.db", "desktop.ini"}
TITLE = re.compile(rb"<title[^>]*>\s*([^<\s][^<]*)</title>", re.I)


class SiteError(ValueError):
    """The archive is not accepted; the message tells the administrator which file and why."""


def _entries(data: bytes, filename: str):
    """(name, kind, size, read) of every entry; kind — file, dir or other (links, devices)."""
    name = filename.lower()
    if name.endswith(".zip") or data[:4] == b"PK\x03\x04":
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise SiteError("Архив zip повреждён") from exc
        for info in archive.infolist():
            mode = (info.external_attr >> 16) & 0o170000
            kind = "dir" if info.is_dir() else ("other" if mode and mode != 0o100000 else "file")
            yield info.filename, kind, info.file_size, (lambda i=info: archive.read(i))
        return
    if name.endswith((".tar.gz", ".tgz")) or data[:2] == b"\x1f\x8b":
        try:
            archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
            members = archive.getmembers()
        except (tarfile.TarError, OSError, EOFError) as exc:
            raise SiteError("Архив tar.gz повреждён") from exc
        for m in members:
            kind = "dir" if m.isdir() else ("file" if m.isfile() else "other")
            yield m.name, kind, m.size, (lambda m=m: archive.extractfile(m).read())
        return
    raise SiteError("Нужен архив .zip или .tar.gz")


def read_archive(data: bytes, filename: str) -> dict[str, bytes]:
    """The site from an uploaded archive, checked file by file; the files of the only top folder move to the root."""
    if len(data) > MAX_ARCHIVE:
        raise SiteError("Архив больше 20 МБ")
    files: dict[str, bytes] = {}
    total = 0
    for raw, kind, size, read in _entries(data, filename):
        path = raw.replace("\\", "/")
        if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
            raise SiteError(f"{raw}: абсолютный путь")
        norm = posixpath.normpath(path)
        parts = [p for p in norm.split("/") if p not in ("", ".")]
        if not parts:
            continue
        if ".." in parts:
            raise SiteError(f"{raw}: путь выходит за пределы сайта")
        if any(p.lower() in SERVICE for p in parts):
            continue  # macOS and Windows leave these in archives: skipped, not an error
        if any(p.startswith(".") for p in parts):
            raise SiteError(f"{raw}: скрытые и служебные файлы не принимаются")
        if kind == "dir":
            continue
        if kind != "file":
            raise SiteError(f"{raw}: ссылки и особые файлы не принимаются")
        ext = posixpath.splitext(parts[-1].lower())[1]
        if ext not in ALLOWED:
            raise SiteError(f"{raw}: файлы «{ext or 'без расширения'}» не принимаются — только статичный сайт (html, css, js, картинки, шрифты, видео)")
        if not re.fullmatch(r"[A-Za-z0-9._~@()+ -]+", parts[-1]) or any(not re.fullmatch(r"[A-Za-z0-9._~@()+ -]+", p) for p in parts):
            raise SiteError(f"{raw}: в именах — латинские буквы, цифры, точка, дефис и подчёркивание")
        total += size
        if total > MAX_UNPACKED or len(files) >= MAX_FILES:
            raise SiteError("Сайт больше 60 МБ или 800 файлов в распакованном виде")
        body = read()
        if len(body) != size:
            raise SiteError(f"{raw}: размер не совпадает с заголовком архива")
        files["/".join(parts)] = body
    tops = {p.split("/", 1)[0] for p in files}
    if "index.html" not in files and len(tops) == 1 and all("/" in p for p in files):
        top = tops.pop()
        files = {p.split("/", 1)[1]: b for p, b in files.items()}
        if "index.html" not in files:
            raise SiteError(f"В папке «{top}» нет index.html")
    if "index.html" not in files:
        raise SiteError("Нет index.html в корне архива или в единственной папке")
    if not TITLE.search(files["index.html"][:200_000]):
        raise SiteError("У index.html нет <title>: без него страница выглядит как заглушка")
    return files


def page_title(files: dict[str, bytes]) -> str:
    m = TITLE.search(files.get("index.html", b"")[:200_000])
    return html.unescape(m.group(1).decode("utf-8", "replace").strip())[:120] if m else ""


def pack(files: dict[str, bytes]) -> bytes:
    """The site as tar.gz with fixed owners, modes and times (the same site gives the same bytes)."""
    out = io.BytesIO()
    # The gzip header carries a time too: tarfile's «w:gz» stamps «now», so the same site uploaded a second later
    # got another id and a second entry in the list. mtime=0 makes the bytes depend on the files only.
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as packed, tarfile.open(fileobj=packed, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(files):
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.mtime, info.uid, info.gid = len(files[path]), 0o644, 0, 0, 0
            tar.addfile(info, io.BytesIO(files[path]))
    return out.getvalue()
