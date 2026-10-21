# Домашнее задание 3

Вариант 8: программист, разработчик Frontend.
Обработка вакансий в RustFS с помощью MapReduce и DuckDB, сравнение производительности, анализ зарплат и регионов.

[Отчёт](output/pdf/Dubovik_Nikita_variant8_hw3.pdf) · [Результаты](output/)

## Запуск

Нужны Python 3.12 и Docker Desktop. Команды выполняются из `hw3`, рядом с исходным CSV `it_vacancies_2024.csv` и папкой `hh` с JSON.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe scripts/init_env.py
docker compose up -d
.venv/Scripts/python.exe -m frontend_lake.storage
.venv/Scripts/python.exe -m frontend_lake.pipeline
.venv/Scripts/python.exe -m frontend_lake.analytics
```
