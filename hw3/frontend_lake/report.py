"""Build the report in the author's dark, serif homework style."""

import csv
import json
import math
import os
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .common import CONFIG, ROOT

OUT = ROOT / "output"
WIDTH = A4[0] - 64
BG = colors.HexColor("#0A101D")
PANEL = colors.HexColor("#0F1929")
HEADER = colors.HexColor("#1C2940")
BORDER = colors.HexColor("#293B55")
TEXT = colors.HexColor("#EDF1FA")
CYAN = colors.HexColor("#79DCFF")
MUTED = colors.HexColor("#B8C5DC")
FOOT = colors.HexColor("#7285A2")
PURPLE = colors.HexColor("#A78BFA")


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def num(value, decimals=0):
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def clean(text):
    text = str(text)
    for dash in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212":
        text = text.replace(dash, "-")
    if chr(59) in text:
        raise ValueError("A semicolon is not allowed in report text")
    return text


def register_fonts():
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if (fonts / "times.ttf").exists():
        files = {"Text": "times.ttf", "Bold": "timesbd.ttf", "Mono": "consola.ttf"}
    else:
        fonts = Path("/usr/share/fonts/truetype/dejavu")
        files = {
            "Text": "DejaVuSerif.ttf",
            "Bold": "DejaVuSerif-Bold.ttf",
            "Mono": "DejaVuSansMono.ttf",
        }
    for name, filename in files.items():
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily(
        "Text", normal="Text", bold="Bold", italic="Text", boldItalic="Bold"
    )


def main():
    register_fonts()
    styles = {
        "body": ParagraphStyle(
            "body", fontName="Text", fontSize=11.5, leading=15.6, textColor=TEXT, spaceAfter=10
        ),
        "small": ParagraphStyle(
            "small", fontName="Text", fontSize=9.4, leading=12.5, textColor=MUTED, spaceAfter=8
        ),
        "title": ParagraphStyle(
            "title", fontName="Bold", fontSize=22, leading=26, textColor=TEXT, spaceAfter=15
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="Bold",
            fontSize=14,
            leading=18,
            textColor=CYAN,
            spaceBefore=8,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "cover": ParagraphStyle(
            "cover", fontName="Bold", fontSize=29, leading=33, textColor=TEXT, spaceAfter=18
        ),
        "label": ParagraphStyle(
            "label", fontName="Text", fontSize=10.5, leading=14, textColor=CYAN, spaceAfter=12
        ),
        "code": ParagraphStyle(
            "code", fontName="Mono", fontSize=8, leading=11, textColor=TEXT, spaceAfter=11
        ),
    }
    story = []

    def p(text, style="body"):
        story.append(Paragraph(clean(text), styles[style]))

    def title(text):
        story.append(PageBreak())
        p(text, "title")

    def h(text):
        p(text, "subtitle")

    def code(text):
        story.append(Preformatted(clean(text), styles["code"]))

    def table(headers, rows, widths, size=9.5, padding=7):
        cell = ParagraphStyle(
            "cell", fontName="Text", fontSize=size, leading=size + 3, textColor=TEXT
        )
        data = [[Paragraph(escape(clean(x)), cell) for x in headers]]
        data += [[Paragraph(escape(clean(x)), cell) for x in row] for row in rows]
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                    ("BACKGROUND", (0, 0), (-1, 0), HEADER),
                    ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.7, CYAN),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.35, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), padding),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                ]
            )
        )
        story.extend([t, Spacer(1, 12)])

    def screenshot(name, caption, height=300):
        path = OUT / "screenshots" / name
        from PIL import Image as PILImage

        with PILImage.open(path) as im:
            w, ht = im.size
        scale = min(WIDTH / w, height / ht)
        story.append(Image(str(path), width=w * scale, height=ht * scale, hAlign="LEFT"))
        story.append(Spacer(1, 7))
        p(caption, "small")

    audit = read("audit.json")
    env = read("environment.json")
    metrics = read("benchmark_summary.json")
    attempts = read("benchmark_raw.json")
    manifest = read("manifest.json")
    prep = read("preparation.json")
    extremes = read("salary_extremes.json")
    canonical = read("salary_extremes_canonical.json")
    regions = read("regions.json")
    counts = {cap: read(f"counts/mr_{cap or 'all'}.json") for cap in CONFIG["stack_sizes"]}
    full = counts[0]
    lookup = {(r["method"], r["cap"]): r for r in metrics}
    before = lookup["duck_csv", 0]
    after = lookup["duck_parquet", 0]
    speed = before["median_wall_seconds"] / after["median_wall_seconds"]
    saving = before["median_wall_seconds"] - after["median_wall_seconds"]
    names = {"mr": "MapReduce", "duck_csv": "DuckDB CSV", "duck_parquet": "DuckDB Parquet"}
    mr = lookup["mr", 0]
    overlap = max(mr["min_wall_seconds"], before["min_wall_seconds"]) <= min(
        mr["max_wall_seconds"], before["max_wall_seconds"]
    )
    comparison_note = (
        "На CSV времена MapReduce и DuckDB близки, диапазоны трёх попыток перекрываются."
        if overlap
        else "Для сравнения скоростей на CSV я использую медианы и диапазоны из таблицы."
    )
    sample_count = len(read("storage_evidence.json")["json_download_sha256_samples"])
    alias_higher = canonical["3_higher"][0]
    alias_lower = canonical["3_lower"][0]
    demand_rows = list(csv.DictReader((OUT / "region_skills.csv").open(encoding="utf-8-sig")))
    js_first = float(
        next(
            row["demand_pct"]
            for row in demand_rows
            if row["region"] == regions[0]["region"] and row["skill"] == "javascript"
        )
    )
    js_last = float(
        next(
            row["demand_pct"]
            for row in demand_rows
            if row["region"] == regions[2]["region"] and row["skill"] == "javascript"
        )
    )
    experience_first = (
        100 * regions[0]["experience"].get("От 3 до 6 лет", 0) / regions[0]["vacancies"]
    )
    experience_last = (
        100 * regions[2]["experience"].get("От 3 до 6 лет", 0) / regions[2]["vacancies"]
    )

    story.append(Spacer(1, 142))
    p("ДОМАШНЕЕ ЗАДАНИЕ", "label")
    p("Обработка Frontend-вакансий<br/>в RustFS", "cover")
    story.append(HRFlowable(width=130, thickness=3, color=CYAN, hAlign="LEFT", spaceAfter=30))
    p("MapReduce, SQL и сравнение производительности")
    p("<b>Выполнил Дубовик Никита</b>")
    p("Индивидуальный вариант 8", "small")
    story.append(Spacer(1, 15))
    cards = [
        [
            Paragraph(
                "<b>01 Хранилище</b><br/><br/>Четыре папки и данные в hh-lake", styles["body"]
            ),
            Paragraph(
                "<b>02 Подсчёт навыков</b><br/><br/>Навыки, пары и тройки двумя способами",
                styles["body"],
            ),
        ],
        [
            Paragraph(
                "<b>03 Сравнение подходов</b><br/><br/>Время, память и переход на Parquet",
                styles["body"],
            ),
            Paragraph(
                "<b>04 Анализ вакансий</b><br/><br/>Зарплаты и сравнение трёх регионов",
                styles["body"],
            ),
        ],
    ]
    card_table = Table(cards, colWidths=[WIDTH / 2, WIDTH / 2], rowHeights=[88, 88])
    card_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("GRID", (0, 0), (-1, -1), 0.7, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 13),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )
    story.append(card_table)

    title("Что было сделано")
    p(
        f"""Я развернул RustFS на четырёх папках и загрузил исходный CSV с ИТ-вакансиями. В этот раз использовал весь каталог hh, поэтому в хранилище находятся все {num(manifest["json_count"])} JSON. Для расчётов выбрал только вакансии своего варианта, программистов и разработчиков Frontend."""
    )
    table(
        ["Данные", "Количество", "Размер, байт"],
        [
            ["Исходный CSV", num(audit["source_rows"]) + " строк", num(manifest["csv"]["bytes"])],
            [
                "JSON из каталога hh",
                num(manifest["json_count"]) + " файлов",
                num(manifest["json_bytes"]),
            ],
            [
                "Отобранные Frontend-вакансии",
                num(audit["frontend_rows"]) + " строк",
                num(audit["frontend_object"]["bytes"]),
            ],
        ],
        [235, 140, WIDTH - 375],
    )
    h("Запуск хранилища")
    code(
        ".venv/Scripts/python.exe scripts/init_env.py\ndocker compose up -d\n.venv/Scripts/python.exe -m frontend_lake.storage"
    )
    p(
        "Для опыта использовал RustFS 1.0.0 в Docker. Папки /data/vol1, /data/vol2, /data/vol3 и /data/vol4 подключены через каталог storage. S3 доступен на порту 9010, консоль на порту 9011."
    )
    screenshot(
        "status.png",
        "Рисунок 1. В консоли RustFS видны один доступный сервер и четыре доступные папки.",
        245,
    )
    p(
        "Все папки находятся на одном компьютере и общем накопителе. Такая схема подходит для учебного опыта, но не защищает от отказа физического диска.",
        "small",
    )

    title("Данные в хранилище")
    p(
        f"""В RustFS создан бакет {CONFIG["bucket"]}. CSV загружен одним объектом в {CONFIG["raw_key"]}. Каждый JSON сохранён отдельным объектом в raw/hh. Дополнительно я сохранил отобранные {num(audit["frontend_rows"])} вакансий в {audit["frontend_object"]["key"]}."""
    )
    screenshot(
        "raw_csv.png",
        f"""Рисунок 2. В бакете {CONFIG["bucket"]} видны исходный CSV размером {num(manifest["csv"]["bytes"] / 1024**2, 1)} МиБ и папка hh с JSON.""",
        340,
    )
    h("Проверка загрузки")
    p(
        f"""После загрузки я скачал CSV из S3 и сравнил SHA-256 с исходным файлом. Хеши совпали. Для всех {num(manifest["json_count"])} JSON проверены размеры объектов. Для {sample_count} файлов дополнительно сравнено содержимое по SHA-256."""
    )
    code(
        f"""CSV SHA-256: совпал
JSON: размеры {num(manifest["json_count"])} из {num(manifest["json_count"])} совпали
JSON: SHA-256 выбранных файлов совпал ({sample_count})"""
    )
    p(
        f"""Список объектов, размеры и хеши сохранены в output/manifest.json и output/storage_evidence.json. В JSON-архиве фильтру соответствуют {num(audit["raw_json_frontend"])} вакансий. Я не объединял этот архив с CSV, чтобы не посчитать одну вакансию дважды. Оба способа расчёта читают один и тот же CSV."""
    )

    title("Как отобраны вакансии варианта 8")
    p(
        "В задании указан вариант «Программист, разработчик Frontend». Дополнительного фильтра не было. Я оставил строки, где роль точно равна «Программист, разработчик», а в названии явно написано Frontend или его русское написание."
    )
    code(
        "WHERE strip_whitespace(role) = 'Программист, разработчик'\n  AND regexp_matches(lower(name),\n  '(^|[^a-zа-яё])(front[ -]*end|фронт[ -]*[еэ]нд)([^a-zа-яё]|$)')"
    )
    p(
        "Фильтр учитывает Frontend, Front-end, Front end, Фронтенд и Фронтэнд в любом регистре. React developer без слова Frontend не включается. Frontend/Fullstack включается, потому что направление Frontend указано прямо. Отбор по роли и названию записан отдельно в Python и SQL."
    )
    table(
        ["Проверка", "Результат"],
        [
            ["Строк в исходном CSV", num(audit["source_rows"])],
            ["Вакансий Frontend", num(audit["frontend_rows"])],
            ["Уникальных пар источник и ID", num(audit["frontend_unique_ids"])],
            ["Вакансий без заполненных навыков", num(audit["no_skills"])],
            ["Максимальный размер стека", audit["max_skills"]],
            [
                "Период публикаций в исходном CSV",
                f"{audit['published_min']} ... {audit['published_max']}",
            ],
        ],
        [335, WIDTH - 335],
    )
    h("Подготовка навыков")
    p(
        "Я разделяю поле key_skills по точке с запятой, убираю пробельные символы по краям и привожу названия к нижнему регистру. SQL-функция strip_whitespace учитывает те же пробелы, табуляции и переносы строк, что и Python. Повторения внутри одной вакансии удаляю. Затем сортирую список и беру первые 5, первые 10 или все навыки."
    )
    p(
        "Эти три размера нужны для сравнения количества сочетаний. Алфавитный порядок не означает важность навыка. Зарплаты и регионы я анализирую по полному стеку. В основных частотах react и react.js остаются разными метками. Проверка синонимов выполнена отдельно."
    )

    title("Два способа подсчёта")
    h("Собственный MapReduce")
    p(
        "Программа открывает CSV через boto3 GetObject. Буфер чтения составляет 1 МиБ. После разбора CSV строки собираются в чанки по 1 000 записей. Так переносы строк в кавычках и границы UTF-8 не разрывают записи."
    )
    p(
        "Для каждой подходящей вакансии Map создаёт навыки, пары и тройки. Локальный счётчик складывает частоты внутри чанка. Reduce объединяет счётчики всех чанков. Весь CSV в память не загружается, но память всё равно растёт с числом уникальных сочетаний."
    )
    p(
        "Это моя одноузловая реализация модели MapReduce. Распределённый кластер вычислителей в этом опыте не разворачивался."
    )
    h("DuckDB")
    p(
        "DuckDB читает тот же объект S3 через расширение httpfs. Запрос самостоятельно отбирает Frontend-вакансии и готовит списки навыков. UNNEST разворачивает список вместе с позицией каждого навыка."
    )
    code(
        "SELECT a.skill, b.skill, c.skill, count(*)\nFROM expanded a\nJOIN expanded b ON a.rid=b.rid AND a.pos<b.pos\nJOIN expanded c ON a.rid=c.rid AND b.pos<c.pos\nGROUP BY a.skill, b.skill, c.skill"
    )
    p(
        "Позиция первого навыка должна быть меньше позиции второго, а позиция второго меньше позиции третьего. Так каждая неупорядоченная тройка получается один раз. Для пар используется соединение двух списков. В SQL нет вызовов Python и чтения готовых результатов MapReduce."
    )
    h("Как проверено совпадение")
    p(
        f"""Я сравнил полный словарь сочетаний и частот, а также ID отобранных вакансий. Одних общих сумм было бы недостаточно. Все {len(attempts)} результатов совпали с эталоном для своего размера стека. Хеши словарей сохранены в output/verification.json."""
    )

    title("Частоты и рост числа сочетаний")
    table(
        ["Стек", "Навыки", "Пары", "Тройки", "Разных навыков", "Разных пар", "Разных троек"],
        [
            [
                cap or "все",
                *[num(x) for x in counts[cap]["sum_frequencies"]],
                *[num(x) for x in counts[cap]["unique_combinations"]],
            ]
            for cap in CONFIG["stack_sizes"]
        ],
        [39, 75, 75, 85, 85, 85, WIDTH - 444],
        9,
        6,
    )
    p(
        "В первых трёх числовых столбцах показаны суммы частот. Если одинаковая пара встретилась в ста вакансиях, она даёт сто упоминаний. В остальных столбцах указано количество разных сочетаний."
    )
    p(
        "Вакансия с m разными навыками даёт m одиночных навыков, m(m-1)/2 пар и m(m-1)(m-2)/6 троек. Поэтому добавление навыков особенно сильно увеличивает число троек."
    )
    table(
        ["Навыков в вакансии", "Пар", "Троек"],
        [[m, num(math.comb(m, 2)), num(math.comb(m, 3))] for m in (5, 10, 20, 30)],
        [220, 155, WIDTH - 375],
    )
    p(
        f"""При переходе от стека 5 к полному стеку число пар выросло с {num(counts[5]["sum_frequencies"][1])} до {num(full["sum_frequencies"][1])}, а троек с {num(counts[5]["sum_frequencies"][2])} до {num(full["sum_frequencies"][2])}. Для стека 5 троек меньше, чем пар, потому что часть вакансий содержит меньше пяти заполненных навыков."""
    )
    h("Самые частые сочетания полного стека")
    table(
        ["Тип", "Сочетание", "Вакансий"],
        [
            [label, " + ".join(r["skills"]), num(r["frequency"])]
            for k, label in [(1, "Навык"), (2, "Пара"), (3, "Тройка")]
            for r in sorted(
                [x for x in full["records"] if x["k"] == k],
                key=lambda x: (-x["frequency"], x["skills"]),
            )[:2]
        ],
        [65, 365, WIDTH - 430],
        9.5,
        5,
    )

    title("Как измерены время и память")
    p(
        f"""Для каждого способа и размера стека я сделал по {CONFIG["repeats"]} запуска в новом процессе Python. Всего получилось {len(attempts)} попыток. Запуски шли последовательно, порядок способов менялся между повторениями."""
    )
    p(
        "Полное время включает запуск процесса, импорт библиотек, чтение из S3, отбор вакансий, подсчёт и запись результата. Именно его я использую для сравнения. Время внутри рабочего процесса до записи JSON сохранено отдельно в benchmark_raw.csv."
    )
    p(
        "Память измерялась через psutil каждые 10 мс. Для процессов дерева берётся сумма их OS peak_wset. Это верхняя оценка одновременного пика, потому что максимумы разных процессов могли наступить в разное время. Она включает нативную память DuckDB. Память контейнера RustFS в неё не входит."
    )
    p(
        f"Среда опыта: Python {env['python'].split()[0]}, DuckDB {env['versions']['duckdb']}, Docker {env['docker_version']}. На компьютере {env['logical_cpus']} логических CPU и {num(env['ram_gib'], 1)} ГиБ ОЗУ. DuckDB использует {CONFIG['duckdb_threads']} потока с ограничением памяти {CONFIG['duckdb_memory_limit']}."
    )
    p(
        "Кэши ОС и RustFS я не сбрасывал. Поэтому результаты относятся к повторным запускам с прогретыми кэшами. На компьютере работали фоновые процессы и другие контейнеры. Показатель docker stats сохранён как отдельный снимок, а не как пик памяти хранилища."
    )
    table(
        ["Способ", "Стек", "Время, с", "Разброс, с", "Память, МиБ"],
        [
            [
                names[r["method"]],
                r["cap"] or "все",
                num(r["median_wall_seconds"], 3),
                f"{num(r['min_wall_seconds'], 3)}-{num(r['max_wall_seconds'], 3)}",
                num(r["median_peak_rss_mib"], 1),
            ]
            for r in metrics
        ],
        [120, 40, 80, 130, WIDTH - 370],
        9,
        6,
    )
    p(
        f"""Время и память в таблице показаны как медианы {CONFIG["repeats"]} попыток. Разброс показывает минимальное и максимальное время. {comparison_note} Медиана памяти MapReduce составляет {num(mr["median_peak_rss_mib"], 1)} МиБ, DuckDB на CSV {num(before["median_peak_rss_mib"], 1)} МиБ."""
    )

    title("Все попытки профилирования")
    table(
        ["Способ", "Стек", "Попытка", "Время, с", "Память, МиБ"],
        [
            [
                names[r["method"]],
                r["cap"] or "все",
                r["repeat"],
                num(r["wall_seconds"], 3),
                num(r["peak_rss_mib"], 1),
            ]
            for r in sorted(attempts, key=lambda x: (x["method"], x["cap"], x["repeat"]))
        ],
        [145, 45, 75, 120, WIDTH - 385],
        9.3,
        4.6,
    )
    p(
        "Для каждой попытки сохранены команда, вывод программы и код завершения. Эти файлы находятся в output/logs. В output/benchmark_raw.csv лежат все измерения, в output/benchmark_summary.csv находятся сводные значения.",
        "small",
    )

    title("Оптимизация через Parquet")
    p(
        "Я подготовил Parquet со сжатием ZSTD. В нём оставлены все исходные строки и 11 столбцов, которые нужны для расчётов. Длинные описания вакансий и другие ненужные поля исключены. Frontend заранее не отбирался, фильтр выполняется при каждом запросе."
    )
    p(
        "Parquet создан из исходного CSV в S3 и загружен обратно в prepared/vacancies.parquet. Запрос считает те же навыки, пары и тройки. Полные результаты для трёх размеров стека совпали с CSV и MapReduce."
    )
    table(
        ["Полный стек", "CSV", "Parquet"],
        [
            [
                "Медиана времени, с",
                num(before["median_wall_seconds"], 3),
                num(after["median_wall_seconds"], 3),
            ],
            [
                "Медиана пика памяти, МиБ",
                num(before["median_peak_rss_mib"], 1),
                num(after["median_peak_rss_mib"], 1),
            ],
            ["Размер объекта, байт", num(manifest["csv"]["bytes"]), num(prep["bytes"])],
            ["Количество попыток", CONFIG["repeats"], CONFIG["repeats"]],
        ],
        [245, 140, WIDTH - 385],
    )
    p(
        f"Время уменьшилось в {num(speed, 2)} раза. Память клиента уменьшилась в {num(before['median_peak_rss_mib'] / after['median_peak_rss_mib'], 2)} раза. Размер объекта стал меньше в {num(manifest['csv']['bytes'] / prep['bytes'], 2)} раза."
    )
    h("Цена подготовки")
    p(
        f"Создание и загрузка Parquet заняли {num(prep['prepare_seconds'], 3)} с. Это время не входит в последующие запросы. "
        + (
            f"При экономии {num(saving, 3)} с на запрос подготовка окупается примерно после {math.ceil(prep['prepare_seconds'] / saving)} запросов полного стека."
            if saving > 0
            else "В этих запусках подготовка по времени не окупилась."
        )
    )
    p(
        f"""Ускорение связано сразу с форматом, сжатием и исключением ненужных столбцов. Я не разделял вклад каждого фактора. Для одного запроса нужно учитывать время подготовки целиком. По памяти у MapReduce получилось {num(mr["median_peak_rss_mib"], 1)} МиБ, у DuckDB на Parquet {num(after["median_peak_rss_mib"], 1)} МиБ."""
    )

    title("Как сравнивается зарплата")
    p(
        "Для сравнения я оставил только рублёвые зарплаты с явным признаком «на руки». Это currency=RUR и gross=false. Зарплаты до налога, другие валюты и неизвестный налоговый статус не смешиваются с этой выборкой."
    )
    p(
        "Если заданы обе границы, использую середину диапазона. Если указана только одна граница, беру её как приближение. Пустые, неположительные, нечисловые и перевёрнутые диапазоны исключаю. Отдельного поля периода выплаты в данных нет, поэтому месячная трактовка остаётся допущением."
    )
    table(
        ["Показатель", "Значение"],
        [
            ["Вакансий с подходящей зарплатой", num(audit["paid_rur_net"])],
            [
                "Доля от всех Frontend-вакансий",
                num(100 * audit["paid_rur_net"] / audit["frontend_rows"], 1) + "%",
            ],
            ["Общая медиана, руб.", num(audit["salary_median"])],
            ["Диапазонов с двумя границами", num(audit["closed_ranges_count"])],
            ["Их медиана, руб.", num(audit["closed_ranges_median"])],
            ["Только нижняя граница", num(audit["open_lower_only"])],
            ["Только верхняя граница", num(audit["open_upper_only"])],
        ],
        [365, WIDTH - 365],
    )
    p(
        f"""Для каждого сочетания сравниваю медиану вакансий со всеми его навыками и медиану остальных вакансий зарплатной выборки. Разница равна первой медиане минус вторая. В группе с сочетанием должно быть не меньше {CONFIG["salary_min_support"]} вакансий, в группе без него не меньше {CONFIG["salary_min_complement"]}."""
    )
    p(
        f"""Далее n показывает размер группы с сочетанием. Группа без него равна {num(audit["paid_rur_net"])} минус n. Столбец «С» содержит медиану с навыками, «Без» содержит медиану без сочетания. Разница не доказывает причинного влияния навыка. На неё могут влиять опыт, регион и компания."""
    )
    p(
        f"""Я проверяю много пересекающихся сочетаний и не делаю поправку на множественные сравнения. Поэтому это поиск наблюдений в данных, а не доказательство статистической значимости. Медиана только закрытых диапазонов составляет {num(audit["closed_ranges_median"])} рублей вместо {num(audit["salary_median"])} рублей. Открытые границы влияют на результат."""
    )

    for k, label in [(2, "Пары"), (3, "Тройки")]:
        title(f"{label} навыков и зарплата")
        for direction, heading in [
            ("higher", "Наибольшая положительная разница"),
            ("lower", "Наибольшая отрицательная разница"),
        ]:
            h(heading)
            table(
                ["Навыки", "n", "С, руб.", "Без, руб.", "Разница, руб."],
                [
                    [
                        r["skills"],
                        r["support_paid"],
                        num(r["median_with"]),
                        num(r["median_without"]),
                        num(r["delta_rub"]),
                    ]
                    for r in extremes[f"{k}_{direction}"][:5]
                ],
                [240, 35, 85, 85, WIDTH - 445],
                9.3,
                7,
            )
        higher = extremes[f"{k}_higher"][0]
        lower = extremes[f"{k}_lower"][0]
        p(
            f"Самая большая положительная разница получилась для {escape(higher['skills'])}. Медиана выше на {num(higher['delta_rub'])} рублей при n={higher['support_paid']}. Для {escape(lower['skills'])} медиана ниже на {num(abs(lower['delta_rub']))} рублей при n={lower['support_paid']}."
        )
        p(
            "Эти результаты относятся к исходным меткам навыков. Медианы и размеры показанных групп я дополнительно проверил независимым SQL-запросом. Полный список находится в output/salary_associations.csv."
        )
        if k == 3:
            p(
                "В верхней части есть react и react.js внутри одной тройки. Они обозначают одну технологию, поэтому такой результат нельзя считать сочетанием трёх независимых компетенций. Ниже я отдельно проверяю влияние синонимов."
            )

    title("Что меняется при объединении синонимов")
    p(
        "Для дополнительной проверки я объединил react.js и reactjs в react, vue.js и vuejs в vue, angular.js в angularjs. Angular и AngularJS оставил разными технологиями. После замены снова удалил повторы внутри каждой вакансии."
    )
    p(
        f"""Основные контрольные частоты MapReduce и SQL не меняются. Это отдельная проверка зарплатного анализа с теми же правилами отбора зарплат и порогом {CONFIG["salary_min_support"]} вакансий."""
    )
    for k, label in [(2, "Пары"), (3, "Тройки")]:
        h(label + " после объединения синонимов")
        rows = [("Выше", r) for r in canonical[f"{k}_higher"][:3]] + [
            ("Ниже", r) for r in canonical[f"{k}_lower"][:3]
        ]
        table(
            ["Разница", "Навыки", "n", "С, руб.", "Без, руб."],
            [
                [
                    num(r["delta_rub"]),
                    r["skills"],
                    r["support_paid"],
                    num(r["median_with"]),
                    num(r["median_without"]),
                ]
                for direction, r in rows
            ],
            [80, 245, 35, 85, WIDTH - 445],
            9.3,
            6,
        )
    p(
        f"""После объединения синонимов среди троек с наибольшей положительной разницей выделяется {escape(alias_higher["skills"])}. Медиана составляет {num(alias_higher["median_with"])} рублей против {num(alias_higher["median_without"])} рублей у остальных вакансий, n={alias_higher["support_paid"]}."""
    )
    p(
        f"""У {escape(alias_lower["skills"])} медиана составляет {num(alias_lower["median_with"])} рублей против {num(alias_lower["median_without"])} рублей, n={alias_lower["support_paid"]}. Это наблюдение о составе вакансий. Из него не следует, что отдельный навык сам по себе снижает зарплату. Дополнительные таблицы сохранены в salary_associations_canonical.csv и salary_extremes_canonical.json."""
    )

    title("Сравнение трёх регионов")
    p(
        f"""Я выбрал три региона: {", ".join(CONFIG["regions"])}. Регион определяется точным значением area. Для удалённой вакансии город публикации может отличаться от места работы сотрудника."""
    )
    table(
        ["Регион", "Вакансий", "С зарплатой", "Доля, %", "Медиана, руб."],
        [
            [
                r["region"],
                num(r["vacancies"]),
                r["paid_rur_net"],
                num(r["salary_coverage_pct"], 1),
                num(r["median_rur_net"]),
            ]
            for r in regions
        ],
        [145, 85, 95, 75, WIDTH - 400],
        9.5,
        7,
    )
    p(
        "Зарплаты рассчитаны по той же рублёвой выборке на руки. Доля показывает, у какой части вакансий региона есть подходящая зарплата. Это важно, потому что покрытие различается почти вдвое."
    )
    demand = list(csv.DictReader((OUT / "region_skills.csv").open(encoding="utf-8-sig")))
    demand_map = {(r["region"], r["skill"]): r for r in demand}
    selected_skills = []
    for region in CONFIG["regions"]:
        for row in [r for r in demand if r["region"] == region][:5]:
            if row["skill"] not in selected_skills:
                selected_skills.append(row["skill"])
    table(
        ["Навык"] + CONFIG["regions"],
        [
            [skill]
            + [
                f"{demand_map[(region, skill)]['vacancies']} ({num(float(demand_map[(region, skill)]['demand_pct']), 1)}%)"
                if (region, skill) in demand_map
                else "вне первых 15"
                for region in CONFIG["regions"]
            ]
            for skill in selected_skills
        ],
        [100, 140, 150, WIDTH - 390],
        9.4,
        6,
    )
    p(
        f"""Частоты навыков посчитаны среди всех Frontend-вакансий региона. {regions[0]["region"]} даёт {num(regions[0]["vacancies"])} вакансии против {num(regions[1]["vacancies"])} в регионе {regions[1]["region"]} и {num(regions[2]["vacancies"])} в регионе {regions[2]["region"]}. Поэтому для сравнения востребованности я смотрю на доли, а не только на количество упоминаний."""
    )
    p(
        f"""В регионе {regions[2]["region"]} JavaScript указан в {num(js_last, 1)}% вакансий, в регионе {regions[0]["region"]} в {num(js_first, 1)}%. Разница составляет {num(js_last - js_first, 1)} процентного пункта. Доля вакансий с опытом от 3 до 6 лет составляет {num(experience_last, 1)}% и {num(experience_first, 1)}% соответственно. Разный состав опыта может частично объяснять разницу зарплат."""
    )
    p(
        "В знаменатель долей входят и вакансии с пустыми навыками. Поэтому показатели отражают также полноту описаний. Обе региональные таблицы сверены с отдельными SQL-запросами из sql/regions.sql."
    )

    title("Итоги и воспроизведение")
    p(
        f"""MapReduce и DuckDB дали одинаковые частоты навыков, пар и троек для всех трёх стеков. {comparison_note} Переход DuckDB на Parquet ускорил полный расчёт примерно в {num(speed, 2)} раза с учётом указанных условий опыта."""
    )
    p(
        "Для зарплатного сравнения важно разделять валюту, налоговый статус и открытые диапазоны. После объединения синонимов верхние сочетания меняются, поэтому качество меток влияет на выводы. Более высокая зарплата в Москве также сопровождается другой структурой требований к опыту."
    )
    h("Основные команды")
    code(
        ".venv/Scripts/python.exe scripts/init_env.py\ndocker compose up -d\n.venv/Scripts/python.exe -m frontend_lake.storage\n.venv/Scripts/python.exe -m frontend_lake.pipeline\n.venv/Scripts/python.exe -m frontend_lake.analytics\n.venv/Scripts/python.exe scripts/evidence.py\n.venv/Scripts/python.exe -m frontend_lake.report\n.venv/Scripts/python.exe scripts/render_pdf.py\n.venv/Scripts/python.exe scripts/publish_results.py\n.venv/Scripts/python.exe scripts/check_submission.py --remote"
    )
    p(
        f"""Команды запускают Python из виртуального окружения проекта. Исходный код находится в frontend_lake, SQL-запросы в sql. Все {len(attempts)} попыток и выводы команд сохранены в output. Частоты для стеков 5, 10 и всех навыков загружены в hh-lake/results/variant8/counts."""
    )
    target = OUT / "pdf/Dubovik_Nikita_variant8_hw3.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)

    def page_design(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.45)
        canvas.circle(A4[0] + 8, A4[1] + 8, 115, stroke=1, fill=0)
        canvas.circle(-35, -32, 114, stroke=1, fill=0)
        if doc.page > 1:
            canvas.setFont("Text", 10)
            canvas.setFillColor(CYAN)
            canvas.drawString(32, A4[1] - 23, "FRONTEND")
            canvas.setLineWidth(1.6)
            canvas.setStrokeColor(CYAN)
            canvas.line(32, A4[1] - 32, A4[0] - 100, A4[1] - 32)
            canvas.setStrokeColor(PURPLE)
            canvas.line(A4[0] - 100, A4[1] - 32, A4[0] - 32, A4[1] - 32)
        canvas.setFont("Text", 9)
        canvas.setFillColor(FOOT)
        canvas.drawString(32, 22, "Инженерия данных")
        canvas.drawRightString(A4[0] - 32, 22, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=32,
        rightMargin=32,
        topMargin=48,
        bottomMargin=42,
        title="Обработка Frontend-вакансий в RustFS",
        author="Дубовик Никита",
    )
    doc.build(story, onFirstPage=page_design, onLaterPages=page_design)
    print(target)


if __name__ == "__main__":
    main()
