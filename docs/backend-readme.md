# Career Quest — работающий демонстрационный backend

Python 3.10+, FastAPI, SQLite. По умолчанию запускается **синтетический демонстрационный набор**, не данные организаторов. Существующее расчётное ядро сохранено; загрузка отделена в backend/loader.py, сохранение — backend/storage.py. Внешнего AI нет; explanation_source=fallback.

Установка:
```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Запуск из корня проекта:
```sh
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Swagger: http://127.0.0.1:8000/docs. В Authorize введите `demo-employee-1`. Сотрудник: `DEMO_001`. Health публичный. Набор seed: demo/dataset.json; изменения сохраняются в data/demo.sqlite3 и переживают перезапуск.

Основной сценарий на свежей БД:
```sh
curl http://127.0.0.1:8000/health
curl -H 'Authorization: Bearer demo-employee-1' http://127.0.0.1:8000/employees/DEMO_001
curl -H 'Authorization: Bearer demo-employee-1' http://127.0.0.1:8000/employees/DEMO_001/recommendations
curl -X POST -H 'Authorization: Bearer demo-employee-1' -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-design-1' -d '{}' http://127.0.0.1:8000/employees/DEMO_001/activities/DEMO_DESIGN/complete
curl -H 'Authorization: Bearer demo-employee-1' http://127.0.0.1:8000/employees/DEMO_001
```

SYSTEM_DESIGN: 2 → 3; покрытие цели: 60% → 70%. Повтор POST не начисляет прирост. Повторяемое DEMO_MENTOR требует тела `{"participation_id":"mentoring-1"}`. Новое участие — новый participation_id и ключ; сетевой retry — прежние значения.

Для новой демонстрации без удаления старого прогресса задайте новый файл БД:
```sh
CAREER_QUEST_DB=data/demo-fresh.sqlite3 .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Настройки:
- CAREER_QUEST_DB: путь SQLite; по умолчанию data/demo.sqlite3.
- CAREER_QUEST_NORMALIZED_DATA: JSON нашей внутренней схемы Dataset. При настройке демонстрационные токены не включаются. При изменении seed используйте новый файл БД, чтобы не потерять старые выполнения.
- CAREER_QUEST_TOKENS: JSON `{"<secret>":{"role":"employee","employee_id":"<id>"},"<hr-secret>":{"role":"hr"}}`. В демо по умолчанию demo-employee-1/2/3 для DEMO_001/002/003 и demo-hr для HR. Это учебные ключи, не реальная система входа.
- CAREER_QUEST_CORS_ORIGINS: origin через запятую; по умолчанию localhost и 127.0.0.1 на портах 5173 и 3000. Интерфейс на `/` не требует CORS. Для команды на других ноутбуках задайте origin frontend и запускайте с --host 0.0.0.0; URL backend будет с IP вашего ноутбука. Для crypto.randomUUID при удалённом доступе frontend нужен HTTPS.

Тесты: `.venv/bin/python -m pytest -q`. Проверяются расчёты, ограничения доступа, полный сценарий, повтор после перезапуска, разные ключи, отдельные повторяемые участия, конкурентные запросы и отсутствие записей при GET/ошибках.

Контракты: [API](api-contract.md), [AI](ai-contract.md). [Допущения](data-status.md). Готовые JSON: docs/examples/*.demo.json.

Этап frontend добавил импорт внутреннего JSON, HR-агрегации, историю, сохранение цели и интерфейс на `/`. Подробности и запуск на Windows: [frontend-handoff.md](frontend-handoff.md). Пока не реализованы чат, внешняя модель и адаптер формата организаторов.
