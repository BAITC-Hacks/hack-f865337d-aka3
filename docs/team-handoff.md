# Передача Career Quest backend команде

Ветка: https://github.com/BAITC-Hacks/hack-f865337d-aka3/tree/backend-aida

Контракт HTTP: [api-contract.md](api-contract.md). OpenAPI: [openapi.json](openapi.json). Контракт AI: [ai-contract.md](ai-contract.md). Все данные синтетические, не данные организаторов.

## Установка на другом ноутбуке

Требуются Git и Python 3.10+ (на macOS проверено с Python 3.13). Windows-команды приведены для PowerShell; на Windows запуск не проверялся. Выберите новую папку, чтобы не затронуть существующую работу команды.

Одинаково для macOS и Windows:
```sh
git clone --branch backend-aida --single-branch https://github.com/BAITC-Hacks/hack-f865337d-aka3.git career-quest-backend
cd career-quest-backend
```

macOS:
```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell:
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Активация окружения не требуется. requirements-dev.txt включает зависимости сервера и тестов. Запускать из корня клона. Если порт занят, остановите свой предыдущий процесс либо укажите --port 8001 и замените порт во всех URL. Остановка сервера: Ctrl+C.

## Frontend: адреса и авторизация

После локального запуска:
- Health: http://127.0.0.1:8000/health
- Swagger: http://127.0.0.1:8000/docs
- Профиль: http://127.0.0.1:8000/employees/DEMO_001
- Рекомендации: http://127.0.0.1:8000/employees/DEMO_001/recommendations
- Выполнение: POST http://127.0.0.1:8000/employees/DEMO_001/activities/DEMO_DESIGN/complete

Профиль, рекомендации и выполнение требуют заголовок `Authorization: Bearer demo-employee-1`. В Swagger кнопка Authorize принимает `demo-employee-1` без префикса Bearer. Обычный переход в браузере по защищённому URL даст 401 — используйте Swagger или запрос с заголовком. ID сотрудника: DEMO_001; ещё есть DEMO_002 и DEMO_003 с токенами demo-employee-2 и demo-employee-3.

Проверка macOS:
```sh
curl http://127.0.0.1:8000/health
curl -H 'Authorization: Bearer demo-employee-1' http://127.0.0.1:8000/employees/DEMO_001
```

Проверка Windows PowerShell:
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$headers = @{Authorization = 'Bearer demo-employee-1'}
Invoke-RestMethod http://127.0.0.1:8000/employees/DEMO_001 -Headers $headers
```

Frontend пример (токен демонстрационный):
```javascript
const base = 'http://127.0.0.1:8000';
const headers = { Authorization: 'Bearer demo-employee-1' };
const profile = await fetch(`${base}/employees/DEMO_001`, { headers }).then(r => r.json());
// Генерировать один раз для нажатия; при сетевом retry использовать тот же ключ.
const key = crypto.randomUUID();
const completed = await fetch(`${base}/employees/DEMO_001/activities/DEMO_DESIGN/complete`, {
  method: 'POST',
  headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': key },
  body: JSON.stringify({})
}).then(r => r.json());
// completed.profile и completed.recommendations содержат пересчитанное состояние.
```

В интерфейсе проверяйте response.ok до обработки успешного ответа; коды ошибок перечислены в контракте. Повторяемое DEMO_MENTOR требует participation_id в теле. Сетевой retry сохраняет и participation_id, и Idempotency-Key. Новое участие получает новые значения.

На свежем клоне SQLite создаётся автоматически: SYSTEM_DESIGN=2, прогресс=60%. После DEMO_DESIGN: 3 и 70%. На ноутбуке Aida это выполнение уже сохранено; повтор не увеличит навык. Для нового демо без удаления БД используйте новый путь CAREER_QUEST_DB. GET не изменяет данные.

localhost/127.0.0.1 означает ноутбук, на котором открыт браузер. Для подключения к чужому ноутбуку используйте его LAN IP, общую сеть, разрешённый порт и запуск backend с --host 0.0.0.0. CORS по умолчанию допускает http://localhost:5173 и http://localhost:3000. Для иного origin до запуска задайте точный адрес frontend:

macOS:
```sh
export CAREER_QUEST_CORS_ORIGINS='http://localhost:5173,http://127.0.0.1:5173'
```
Windows PowerShell:
```powershell
$env:CAREER_QUEST_CORS_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
```
Если frontend открыт по LAN-адресу, добавьте именно этот origin. Учебные токены предназначены только для синтетического демо.

## AI: факты и результат

Полный вход: [ai-context.demo.json](examples/ai-context.demo.json). Это валидный AIContext на свежем демо; сохранённый живой профиль может отличаться.

Backend умеет формировать `backend.engine.ai_context(dataset, employee_id)`. В будущей интеграции передавать актуальный `Store.snapshot()` после серверной авторизации. HTTP-маршрута AI и вызова модели пока нет; запросы сейчас используют шаблоны.

Верхний уровень входа: contract_version="1.0", profile=Profile, recommendations=Recommendations. Внутри — цель, уровни, разрывы, история похожих активностей, доступные события и вычисленный эффект. Полный JSON и типы даны по ссылкам выше, поля не нужно восстанавливать из сокращённого описания.

Пример ожидаемого ответа: [ai-response.demo.json](examples/ai-response.demo.json). AI возвращает только текст для переданного event_id. Числа, доступность и ранжирование остаются у backend. Объяснение — 1–2000 символов, минимум три фактора; без выдуманных событий и обещания повышения. Неизвестные/повторяющиеся event_id будущий адаптер должен отклонять. При ошибке/таймауте сохранять fallback. Сейчас этот адаптер и таймаут не реализованы.

## Проверено и границы реализации

Работает: четыре прикладных маршрута (health, профиль, рекомендации, complete), SQLite, идемпотентность, отдельные повторяемые участия, доступ employee/HR, CORS, шаблонные объяснения, формирование AIContext. 26 тестов покрывают также конкурентные выполнения, перезапуск и ошибки. Живые health/docs/профиль/рекомендации дают HTTP 200; 401/403 и соответствие OpenAPI текущему коду проверены.

Не реализовано: вызов LLM и обработка его ответа, чат, импорт, HR-агрегации, адаптер организаторского датасета и полноценный вход пользователей. Windows-команды подготовлены, но Windows-среда для проверки отсутствует. Ветка main развивается отдельно; этот handoff не сливает и не перезаписывает изменения команды.
