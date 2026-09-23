import json
import os
import secrets
import time
import csv
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Header, Request, Response, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError

from .engine import profile, recommendations
from .models import Dataset, Profile, Recommendations, CompletionRequest, CompletionResponse, GoalRequest, ChatRequest, ChatResponse, AIContext
from .loader import load_dataset, adapt_import
from .storage import Store, CompletionError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


class Principal(BaseModel):
    role: Literal['employee', 'hr']
    employee_id: str | None = None


class Health(BaseModel):
    status: Literal['ok', 'degraded']
    api_version: str = '1.2'
    data_source: str
    demo: bool
    dataset_loaded: bool
    employees_count: int
    simulation_date: str | None
    message: str | None


def create_app(dataset: Dataset | None = None, tokens: dict | None = None,
               db_path: str | None = None, demo: bool = False, jury_demo: bool = False, ai_service=None) -> FastAPI:
    if dataset is None and os.getenv('CAREER_QUEST_NORMALIZED_DATA'):
        dataset = load_dataset(os.environ['CAREER_QUEST_NORMALIZED_DATA'])
    store = Store(db_path, dataset) if db_path and dataset is not None else None
    configured_tokens = tokens if tokens is not None else json.loads(os.getenv('CAREER_QUEST_TOKENS', '{}'))
    principals = {key: Principal.model_validate(value) for key, value in configured_tokens.items()}
    sessions = {}
    from .ai import AIService
    ai = ai_service or AIService()
    if any(not key or (p.role == 'employee' and not p.employee_id) for key, p in principals.items()):
        raise ValueError('Each token requires a principal; employee requires employee_id')
    app = FastAPI(title='Career Quest Backend', version='1.2.0',
                  description='Демонстрационный backend; данные организаторов не подключены.' if demo else 'Career Quest backend')
    app.add_middleware(CORSMiddleware,
                       allow_origins=os.getenv('CAREER_QUEST_CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000').split(','),
                       allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type', 'Idempotency-Key'])
    bearer = HTTPBearer(auto_error=False)

    @app.middleware('http')
    async def request_limits(request: Request, call_next):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = request.headers.get('origin')
            cookie_auth = bool(request.cookies.get('cq_session')) and not request.headers.get('authorization')
            if (cookie_auth or request.url.path in ('/auth/demo', '/auth/login', '/auth/logout')) and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': {'message': 'Недопустимый Origin. Откройте сайт на том же сервере.'}}, status_code=403)
            size = 0
            parts = []
            async for part in request.stream():
                size += len(part)
                if size > 2 * 1024 * 1024:
                    return JSONResponse({'detail': {'message': 'Запрос больше 2 МБ.'}}, status_code=413)
                parts.append(part)
            request._body = b''.join(parts)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if not request.url.path.startswith('/assets/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def principal(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
        if credentials:
            for token, identity in principals.items():
                if secrets.compare_digest(credentials.credentials.encode(), token.encode()):
                    return identity
        elif request.cookies.get('cq_session'):
            session = sessions.get(request.cookies['cq_session'])
            if session and session[1] > time.time():
                return session[0]
        raise HTTPException(401, detail={'code': 'unauthorized', 'message': 'Требуется вход в Career Quest.'},
                            headers={'WWW-Authenticate': 'Bearer'})

    @app.get('/auth/me')
    def me(identity: Principal = Depends(principal)):
        return identity

    @app.get('/auth/config')
    def auth_config():
        # Only original synthetic profiles are exposed before login; never imported records.
        safe = [{'employee_id': e.employee_id, 'name': e.name, 'role': e.role, 'grade': e.grade}
                for e in dataset.employees] if jury_demo and dataset else []
        return {'jury_demo': jury_demo, 'employees': safe}

    def issue_session(identity, request, response):
        now = time.time()
        for key in list(sessions):
            if sessions[key][1] <= now:
                sessions.pop(key, None)
        if len(sessions) >= 1000:
            raise HTTPException(429, detail={'message': 'Слишком много сессий. Повторите позже.'})
        sessions.pop(request.cookies.get('cq_session'), None)
        sid = secrets.token_urlsafe(32)
        sessions[sid] = (identity, now + 8 * 3600)
        response.set_cookie('cq_session', sid, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=8 * 3600, path='/')
        return identity

    @app.post('/auth/demo')
    def demo_login(request: Request, response: Response, body: Principal):
        if not jury_demo:
            raise HTTPException(404, detail={'message': 'Режим жюри выключен.'})
        if body.role == 'employee' and (not dataset or body.employee_id not in {e.employee_id for e in dataset.employees}):
            raise HTTPException(422, detail={'message': 'Выберите демонстрационного сотрудника.'})
        if body.role == 'hr':
            body.employee_id = None
        return issue_session(body, request, response)

    @app.post('/auth/login')
    def login(request: Request, response: Response, identity: Principal = Depends(principal)):
        return issue_session(identity, request, response)

    @app.post('/auth/logout')
    def logout(request: Request, response: Response):
        sessions.pop(request.cookies.get('cq_session'), None)
        response.delete_cookie('cq_session', path='/')
        return {'status': 'ok'}

    def authorized_data(employee_id: str, identity: Principal = Depends(principal)) -> Dataset:
        if identity.role != 'hr' and identity.employee_id != employee_id:
            raise HTTPException(403, detail={'code': 'forbidden', 'message': 'Нет доступа к этому профилю.'})
        if dataset is None:
            raise HTTPException(503, detail={'code': 'dataset_unavailable', 'message': 'Исходный датасет ещё не загружен.'})
        current = store.snapshot() if store else dataset
        if not any(e.employee_id == employee_id for e in current.employees):
            raise HTTPException(404, detail={'code': 'employee_not_found', 'message': 'Сотрудник не найден.'})
        return current

    @app.get('/health', response_model=Health)
    def health():
        current = store.snapshot() if store else dataset
        return Health(data_source='organizer_synthetic' if dataset and dataset.skill_catalog else 'synthetic_demo' if demo else 'normalized' if dataset else 'unavailable',
                      demo=demo, status='ok' if dataset is not None else 'degraded', dataset_loaded=dataset is not None,
                      employees_count=len(current.employees) if current else 0,
                      simulation_date=str(dataset.simulation_date) if dataset else None,
                      message=('Демонстрационные данные, не датасет организаторов.' if demo else None) if dataset else 'Missing starter-kit dataset; see docs/data-status.md')

    errors = {code: {'description': text} for code, text in
              [(401, 'Missing/invalid token'), (403, 'Forbidden profile'),
               (404, 'Unknown employee in loaded dataset'), (503, 'Dataset unavailable')]}

    @app.get('/employees/{employee_id}', response_model=Profile, responses=errors)
    def employee_profile(employee_id: str, data: Dataset = Depends(authorized_data)):
        return profile(data, employee_id)

    @app.get('/employees/{employee_id}/recommendations', response_model=Recommendations, responses=errors)
    async def employee_recommendations(employee_id: str, data: Dataset = Depends(authorized_data)):
        p = profile(data, employee_id)
        return await ai.explain(AIContext(profile=p, recommendations=recommendations(data, p)))

    @app.post('/employees/{employee_id}/chat', response_model=ChatResponse)
    async def chat(employee_id: str, body: ChatRequest, data: Dataset = Depends(authorized_data)):
        p = profile(data, employee_id)
        r = recommendations(data, p)
        if body.event_id and body.event_id not in {i.event_id for i in r.items}:
            raise HTTPException(422, detail={'message': 'Выберите активность из актуальных рекомендаций.'})
        return await ai.chat(AIContext(profile=p, recommendations=r), body)

    @app.post('/employees/{employee_id}/activities/{event_id}/complete',
              response_model=CompletionResponse,
              responses={**errors, 409: {'description': 'Conflict or unavailable activity'}})
    def complete(employee_id: str, event_id: str, body: CompletionRequest,
                 idempotency_key: str = Header(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$'),
                 data: Dataset = Depends(authorized_data)):
        if store is None:
            raise HTTPException(503, detail={'code': 'storage_unavailable', 'message': 'Хранилище не настроено.'})
        try:
            return store.complete(employee_id, event_id, body, idempotency_key)
        except CompletionError as error:
            raise HTTPException(error.status, detail={'code': error.code, 'message': error.message}) from error

    def hr_data(identity: Principal = Depends(principal)):
        if identity.role != 'hr':
            raise HTTPException(403, detail={'code': 'forbidden', 'message': 'Требуются права HR.'})
        if dataset is None:
            raise HTTPException(503, detail={'code': 'dataset_unavailable', 'message': 'Данные недоступны.'})
        return store.snapshot() if store else dataset

    @app.get('/hr/overview')
    def overview(data: Dataset = Depends(hr_data)):
        deficits, missing, participation = {}, [], []
        for employee in data.employees:
            p = profile(data, employee.employee_id)
            r = recommendations(data, p)
            for gap in p.gaps:
                row = deficits.setdefault(gap.skill_id, {'skill_id': gap.skill_id, 'name': p.skill_names.get(gap.skill_id, gap.skill_id), 'employees_count': 0, 'critical_count': 0})
                row['employees_count'] += 1
                row['critical_count'] += int(gap.critical)
            if not r.items:
                missing.append({'employee_id': p.employee_id, 'name': p.name, 'reason': r.message})
            participation.append({'employee_id': p.employee_id, 'name': p.name,
                                  'completed': sum(h.status == 'completed' for h in p.history),
                                  'in_progress': sum(h.status == 'in_progress' for h in p.history),
                                  'missed': sum(h.status in ('declined', 'dropped', 'no_show') for h in p.history)})
        by_event = []
        for event in data.events:
            rows = [h for h in data.history if h.event_id == event.event_id and h.date <= data.simulation_date]
            by_event.append({'event_id': event.event_id, 'title': event.title,
                             'completed': sum(h.status == 'completed' for h in rows),
                             'in_progress': sum(h.status == 'in_progress' for h in rows),
                             'missed': sum(h.status in ('declined', 'dropped', 'no_show') for h in rows),
                             'overdue': sum(h.status == 'overdue' for h in rows)})
        return {'as_of': data.simulation_date, 'employees_count': len(data.employees), 'event_participation': by_event,
                'skill_deficits': sorted(deficits.values(), key=lambda x: (-x['employees_count'], x['skill_id'])),
                'without_next_step': missing, 'participation': participation}

    @app.post('/imports')
    def import_profiles(body: dict = Body(...), data: Dataset = Depends(hr_data)):
        if store is None:
            raise HTTPException(503, detail={'message': 'Хранилище не настроено.'})
        try:
            return store.import_profiles(adapt_import(body))
        except CompletionError as error:
            raise HTTPException(error.status, detail={'code': error.code, 'message': error.message}) from error
        except ValidationError as error:
            raise HTTPException(422, detail={'code': 'invalid_import', 'message': 'Импорт отклонён: ' + '; '.join(e['msg'] for e in error.errors())}) from error
        except (ValueError, KeyError, TypeError, csv.Error) as error:
            raise HTTPException(422, detail={'code': 'invalid_import', 'message': 'Некорректный формат импорта: проверьте поля JSON и CSV.'}) from error

    @app.post('/employees/{employee_id}/goal', response_model=Profile)
    def set_goal(employee_id: str, body: GoalRequest, data: Dataset = Depends(authorized_data)):
        if store is None:
            raise HTTPException(503, detail={'message': 'Хранилище не настроено.'})
        try:
            return store.set_goal(employee_id, body)
        except CompletionError as error:
            raise HTTPException(error.status, detail={'code': error.code, 'message': error.message}) from error

    frontend = Path(__file__).resolve().parent.parent / 'frontend'
    app.mount('/assets', StaticFiles(directory=frontend), name='frontend')

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(frontend / 'index.html')

    return app


def configured_app():
    normalized_path = os.getenv('CAREER_QUEST_NORMALIZED_DATA')
    dataset = load_dataset(normalized_path or ROOT / 'data' / 'organizer')
    tokens = json.loads(os.getenv('CAREER_QUEST_TOKENS', '{}'))
    return create_app(dataset, tokens, os.getenv('CAREER_QUEST_DB') or str(ROOT / 'data' / 'organizer.sqlite3'),
                      jury_demo=os.getenv('CAREER_QUEST_JURY_DEMO', '').lower() == 'true')


app = configured_app()
