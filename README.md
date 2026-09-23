# hack-f865337d-aka3
Hackathon team repository for aka3

## Career Quest backend

Инструкция запуска и демонстрационный сценарий: [Backend README](docs/backend-readme.md).
Контракты: [API](docs/api-contract.md), [AI](docs/ai-contract.md).

## Интерфейс Career Quest

**Повторный запуск на Windows:** в терминале PowerShell VS Code выполните `.\start-career-quest.cmd`
из корня проекта. Из другой папки
вызовите скрипт по полному пути: он сам выбирает каталог проекта и его `.venv`.
Сайт: **http://127.0.0.1:8000/**. Дождитесь `Application startup complete` и оставьте
терминал открытым. Ctrl+C останавливает сервер; после остановки браузер покажет
`ERR_CONNECTION_REFUSED`. Второй сервер для frontend не нужен.
Скрипт не удаляет базу, не завершает чужие процессы и сообщает о занятом порте
или отсутствующих зависимостях. Настройки `CAREER_QUEST_*` берутся из окружения;
файл `.env` автоматически не загружается (как и при прежнем запуске).

Запуск на Windows (PowerShell в VS Code, из корня репозитория):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Откройте http://127.0.0.1:8000 и нажмите «Открыть демопрофиль».
Frontend — обычные ES-модули JavaScript и CSS, обслуживаемые FastAPI; Node/npm и сборка для запуска не нужны.
Адрес API можно изменить в «Подключение и доступ»; пустое значение использует текущий сервер.

HR: введите учебный `demo-hr`, нажмите «Подключиться», затем вкладку «HR».
Ключ вводится вручную и не включён в frontend. Используйте эти учебные ключи только с синтетическими данными.

[Передача frontend: проверки, ограничения, импорт, изменения API, AI и демо](docs/frontend-handoff.md).
