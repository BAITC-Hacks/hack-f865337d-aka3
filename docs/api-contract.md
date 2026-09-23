# Career Quest API v1.2 — контракт для интеграции

Base URL локально: http://127.0.0.1:8000. Swagger: /docs. Машиночитаемая схема: /openapi.json и docs/openapi.json. Полные типы: backend/models.py. Изменения внешних полей требуют явного уведомления команды.

Изменения v1.1: добавлен POST complete; в health добавлены demo и data_source. Поля профиля и рекомендаций не менялись. По умолчанию сервер загружает явно демонстрационный набор.

Изменения v1.2: Profile дополнен history, available_goals, completion_available, completion_message; Recommendation — repeatable и format. Добавлены POST /imports, GET /hr/overview, POST /employees/{employee_id}/goal. GET /health и поиск профиля читают актуальную SQLite. Корень `/` обслуживает frontend. Чат всё ещё не реализован.

Демо: employee_id=DEMO_001, Bearer token=demo-employee-1. Для DEMO_002/003 — demo-employee-2/3. Демо HR-token=demo-hr. Это публичные учебные ключи только для синтетического набора; при подключении другого источника эти ключи автоматически не включаются.

## Авторизация и ошибки

GET /health публичный. Профиль, рекомендации и выполнение требуют `Authorization: Bearer <token>`.
Токены сопоставляются с ролью и employee_id на сервере через CAREER_QUEST_TOKENS. Передача роли или employee_id в заголовке не даёт прав. Сотрудник читает только себя; HR — любой профиль. Это статические ключи для хакатона, не полноценная система входа. HR-ключ нельзя встраивать в публичный frontend.

401 — нет/неверный токен; 403 — нет доступа; 404 — сотрудник отсутствует в актуальном снимке SQLite; 503 — датасет недоступен. Проверка доступа предшествует поиску профиля.

Формат ошибки: `{"detail":{"code":"employee_not_found","message":"Сотрудник не найден."}}`.

## GET /health

`demo: boolean`, `data_source: synthetic_demo | normalized | unavailable`, `status: "ok" | "degraded"`, `api_version: string`, `dataset_loaded: boolean`, `employees_count: integer`, `simulation_date: ISO date | null`, `message: string | null`.
HTTP 200 означает, что процесс жив. Готовность данных проверяйте по dataset_loaded и status.

## GET /employees/{employee_id}

| Поле | Тип / смысл |
|---|---|
| employee_id, name, role, grade | string |
| as_of, last_review_date | YYYY-MM-DD |
| target | {role: string, grade: string, source: employee или system} либо null |
| target_status | selected, suggested или selection_required |
| skills | object: skill_id → number 0–5, актуальный уровень |
| target_requirements | object: skill_id → number 0–5 |
| gaps | массив {skill_id: string, current: number, required: number, gap: number, critical: boolean}, только положительные разрывы |
| critical_skills | string[], критические навыки цели |
| progress_percent | number 0–100 либо null, если цели нет |
| completed_event_ids | string[], уникальные завершённые активности на as_of |
| applied_participation_ids | string[], участия после оценки, учтённые в уровнях |
| history | Participation[] с дополнительными title и repeatable; записи до as_of включительно, включая in_progress |
| available_goals | GoalDefinition[]: role, grade, requirements, critical_skills |
| completion_available | boolean: дата симуляции строго позже последней оценки; НЕ индивидуальная доступность каждой активности |
| completion_message | string либо null, объясняет блокировку выполнения при совпадении дат |

Прогресс = 100 × Σ min(текущий уровень, требование) / Σ требований. Избыток навыка не компенсирует дефицит другого. Пустые/нулевые требования известной цели дают 100%; отсутствие цели — null.

GET ничего не записывает. Завершённые участия применяются строго после last_review_date и не позже as_of, по дате, при одинаковой дате — по порядку в сохранённой истории. Нормализованная история содержит один итоговый статус на participation_id, а не поток изменений статуса.

## GET /employees/{employee_id}/recommendations

Обёртка: `employee_id: string`, `as_of: date`, `items: Recommendation[]` (0–3), `empty_reason: string | null`, `message: string | null`.

Пустой список — HTTP 200: target_required, target_covered или no_eligible_activities. Frontend выводит message.

| Поле Recommendation | Тип / смысл |
|---|---|
| event_id, title | string |
| repeatable | boolean; новое участие требует нового participation_id |
| format | self_paced или scheduled; длительности в исходной схеме нет |
| facts | Facts, см. ниже |
| expected_skill_changes | массив {skill_id: string, before: number, after: number, delta: number}, только реальные положительные изменения |
| progress_before, progress_after | number 0–100 |
| explanation | string, объяснение для сотрудника |
| explanation_source | ai или fallback; сейчас всегда fallback |

Facts: current_role/current_grade (string), target (как в профиле), addressed_gaps (SkillGap[]), similar_completed/similar_missed (integer), weighted_gap_reduction/history_factor/score (number), eligible_session_date (date|null).

Каждая активность моделируется отдельно от актуального состояния. progress_after разных карточек нельзя складывать. Это ожидаемый эффект при выполнении, не уже начисленные навыки.

Фильтры: добровольность; роль/грейд; предварительные навыки; отсутствие начатого участия; завершённая активность допускается только при repeatable; self_paced не требует сессий, остальные требуют доступную сессию с датой ≥ as_of. В нашей внутренней схеме пустой список roles/grades означает отсутствие ограничения; адаптер должен подтвердить и явно перевести семантику стартового кита.

Наша эвристика (НЕ правило ТЗ): score = weighted_gap_reduction × (1 + history_factor). Критический навык весит 2, прочий — 1. history_factor = 0.1 × (completed − missed) / max(1, completed + missed), для той же категории активности. Missed включает declined/dropped/no_show. Нулевой эффект исключается. При равных баллах сортировка по event_id. Это небольшой фактор выбора, не оценка сотрудника.

## POST /employees/{employee_id}/activities/{event_id}/complete

Требует тот же Bearer token, `Content-Type: application/json`, `Idempotency-Key: <уникальный ключ>` (1–128 символов A–Z, a–z, 0–9, _ или -).

Тело: `{}` для неповторяемой активности; `{"participation_id":"demo-session-1"}` для повторяемой. ID участия — 1–100 символов того же алфавита. Чтобы завершить уже начатое участие, передайте его participation_id. Для неповторяемой активности начатое участие также подхватывается автоматически.

Ответ HTTP 200: `{status: "completed" | "already_completed", participation_id: string, profile: Profile, recommendations: Recommendations}`. Полный JSON: examples/completion.demo.json.

Идемпотентность:
- Сетевой retry отправляет прежние тело, URL и Idempotency-Key. Возвращается точно сохранённый ответ, даже после перезапуска. Если после первого запроса были другие выполнения, этот ответ — исторический снимок; для свежего состояния используйте GET.
- Ключ уникален в пределах сотрудника. Тот же ключ с другой активностью/телом — 409 idempotency_conflict.
- Новый ключ для уже завершённой неповторяемой активности — already_completed без прироста.
- Повторяемая активность с прежним participation_id — already_completed; новый ID означает отдельное участие.
- Проверки и изменение снимка/сохранение ответа проходят одной SQLite-транзакцией BEGIN IMMEDIATE. Параллельные запросы не начисляют один и тот же результат дважды.

404 event_not_found; 409 activity_unavailable / participation_conflict / participation_in_progress / review_date_conflict; 422 participation_required или стандартная ошибка валидации FastAPI (`detail` — массив). Неизвестные поля тела отклоняются. Клиент не передаёт gain, уровень или дату выполнения.

Демовыполнение разрешено для доступной добровольной активности независимо от попадания в top-3. Начатую можно завершить, но она не предлагается как новая рекомендация. Для scheduled будущая сессия завершается сразу датой симуляции — явное допущение демо.

Будущие completed не считаются прошлыми выполнениями и не приводят к already_completed. Явно переданный ID будущего участия отклоняется (409). Записи на дату последней оценки не начисляются повторно; при совпадении даты симуляции с оценкой новое выполнение остаётся заблокированным (409 review_date_conflict), что теперь видно в профиле. Изменение этого правила требует отдельного соглашения о границе оценки.

## POST /employees/{employee_id}/goal

Тело `{ "role": "Backend Engineer", "grade": "Senior" }`. Тот же доступ, что к профилю: сам сотрудник или HR. Цель должна присутствовать в available_goals; иначе 422 unknown_goal. Сохраняет выбор в SQLite с source=employee и возвращает Profile. Для актуальных рекомендаций после изменения выполните GET recommendations. Автоматическое предложение цели при отсутствии выбора сохранено.

## GET /hr/overview

Только серверная роль HR; сотруднику — 403. Ответ: `as_of`, `employees_count`, `skill_deficits: [{skill_id, employees_count, critical_count}]`, `without_next_step: [{employee_id, name, reason}]`, `participation: [{employee_id, name, completed, in_progress, missed}]`.

Агрегации строятся по актуальному снимку. Дефицит — число сотрудников с положительным разрывом; critical_count — число критических разрывов. Участия считаются по записям до даты симуляции включительно; missed объединяет declined/dropped/no_show. Без следующего шага включает отсутствие цели, покрытую цель и отсутствие доступной активности; причины явно различаются.

## POST /imports

Только HR. `Content-Type: application/json`. Поддерживается **внутренний нормализованный формат**, не CSV/Excel и не неизвестный формат организаторов:

```json
{"employees": [{"employee_id":"NEW_001","name":"[ДЕМО] Новый сотрудник","role":"Backend Engineer","grade":"Middle","last_review_date":"2026-09-01","skills":{"PYTHON":3},"target":null}], "history": []}
```

Схемы Employee и Participation — backend/models.py и OpenAPI. Полный пример с историей: frontend/import-example.json (можно скачать из HR). 1–1000 новых сотрудников, до 10000 записей истории. UI ограничивает файл 2 МБ. Только добавление; повторный импорт тех же ID отклоняется, upsert не поддерживается. История относится только к сотрудникам текущего файла, использует уже существующие event_id. Цель должна ссылаться на существующий справочник. Проверяется целиком Dataset; запись одной SQLite-транзакцией, частичный импорт невозможен. Ошибки — 422 с detail; при неудаче данные не меняются.

Ответ: `{ "employee_ids": ["NEW_001"], "employees_imported": 1, "history_imported": 0 }`. Импорт не создаёт учётные данные: HR может сразу открыть профиль, персональные ключи добавляются в CAREER_QUEST_TOKENS на сервере. Для повторного импорта после сетевой неопределённости сначала проверьте HR/GET: импорт не имеет Idempotency-Key, повторные ID безопасно отклоняются.

## Примеры для frontend

Файлы `*.demo.json` получены через TestClient из синтетического DEMO_001 на свежей SQLite:
- profile.demo.json: исходный прогресс 60%, SYSTEM_DESIGN=2.
- recommendations.demo.json: до выполнения.
- completion.demo.json: DEMO_DESIGN выполнен, прогресс 70%, SYSTEM_DESIGN=3.
- profile-after.demo.json и recommendations-after.demo.json: последующие GET.
- ai-context.demo.json: входные факты для участника AI до выполнения.

Файлы `*.test.json` сохранены как прежние вымышленные unit-test примеры TEST_EMPLOYEE; они не загружаются в рабочий сервер. Все примеры — демонстрационные, НЕ данные организаторов.

## Следующий этап — пока не реализован

POST /employees/{employee_id}/chat — только предложенный контракт в frontend-handoff.md. Адаптер стартового кита и внешняя модель пока не подключены. Разграничение доступа employee/HR работает на реализованных endpoint.
