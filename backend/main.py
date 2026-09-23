import json
import os
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .engine import profile, recommendations
from .models import Dataset, Profile, Recommendations, CompletionRequest, CompletionResponse
from .loader import load_dataset
from .storage import Store, CompletionError


class Principal(BaseModel):
    role: Literal['employee', 'hr']
    employee_id: str | None = None


class Health(BaseModel):
    status: Literal['ok', 'degraded']
    api_version: str = '1.1'
    data_source: str
    demo: bool
    dataset_loaded: bool
    employees_count: int
    simulation_date: str | None
    message: str | None


def create_app(dataset: Dataset | None = None, tokens: dict | None = None,
               db_path: str | None = None, demo: bool = False) -> FastAPI:
    if dataset is None and os.getenv('CAREER_QUEST_NORMALIZED_DATA'):
        dataset = load_dataset(os.environ['CAREER_QUEST_NORMALIZED_DATA'])
    store = Store(db_path, dataset) if db_path and dataset is not None else None
    configured_tokens = tokens if tokens is not None else json.loads(os.getenv('CAREER_QUEST_TOKENS', '{}'))
    principals = {key: Principal.model_validate(value) for key, value in configured_tokens.items()}
    if any(not key or (p.role == 'employee' and not p.employee_id) for key, p in principals.items()):
        raise ValueError('Each token requires a principal; employee requires employee_id')
    app = FastAPI(title='Career Quest Backend', version='1.1.0',
                  description='Демонстрационный backend; данные организаторов не подключены.' if demo else 'Career Quest backend')
    app.add_middleware(CORSMiddleware,
                       allow_origins=os.getenv('CAREER_QUEST_CORS_ORIGINS', 'http://localhost:5173,http://localhost:3000').split(','),
                       allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type', 'Idempotency-Key'])
    bearer = HTTPBearer(auto_error=False)

    def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
        if credentials:
            for token, identity in principals.items():
                if secrets.compare_digest(credentials.credentials.encode(), token.encode()):
                    return identity
        raise HTTPException(401, detail={'code': 'unauthorized', 'message': 'Требуется Bearer token.'},
                            headers={'WWW-Authenticate': 'Bearer'})

    def authorized_data(employee_id: str, identity: Principal = Depends(principal)) -> Dataset:
        if identity.role != 'hr' and identity.employee_id != employee_id:
            raise HTTPException(403, detail={'code': 'forbidden', 'message': 'Нет доступа к этому профилю.'})
        if dataset is None:
            raise HTTPException(503, detail={'code': 'dataset_unavailable', 'message': 'Исходный датасет ещё не загружен.'})
        if not any(e.employee_id == employee_id for e in dataset.employees):
            raise HTTPException(404, detail={'code': 'employee_not_found', 'message': 'Сотрудник не найден.'})
        return store.snapshot() if store else dataset

    @app.get('/health', response_model=Health)
    def health():
        return Health(data_source='synthetic_demo' if demo else 'normalized' if dataset else 'unavailable',
                      demo=demo, status='ok' if dataset is not None else 'degraded', dataset_loaded=dataset is not None,
                      employees_count=len(dataset.employees) if dataset else 0,
                      simulation_date=str(dataset.simulation_date) if dataset else None,
                      message=('Демонстрационные данные, не датасет организаторов.' if demo else None) if dataset else 'Missing starter-kit dataset; see docs/data-status.md')

    errors = {code: {'description': text} for code, text in
              [(401, 'Missing/invalid token'), (403, 'Forbidden profile'),
               (404, 'Unknown employee in loaded dataset'), (503, 'Dataset unavailable')]}

    @app.get('/employees/{employee_id}', response_model=Profile, responses=errors)
    def employee_profile(employee_id: str, data: Dataset = Depends(authorized_data)):
        return profile(data, employee_id)

    @app.get('/employees/{employee_id}/recommendations', response_model=Recommendations, responses=errors)
    def employee_recommendations(employee_id: str, data: Dataset = Depends(authorized_data)):
        return recommendations(data, profile(data, employee_id))

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

    return app


def configured_app():
    normalized_path = os.getenv('CAREER_QUEST_NORMALIZED_DATA')
    demo = normalized_path is None
    dataset = load_dataset(normalized_path) if normalized_path else load_dataset()
    demo_tokens = {f'demo-employee-{n}': {'role': 'employee', 'employee_id': f'DEMO_00{n}'} for n in range(1, 4)}
    demo_tokens['demo-hr'] = {'role': 'hr'}
    tokens = json.loads(os.environ['CAREER_QUEST_TOKENS']) if 'CAREER_QUEST_TOKENS' in os.environ else demo_tokens if demo else {}
    return create_app(dataset, tokens, os.getenv('CAREER_QUEST_DB', 'data/demo.sqlite3' if demo else 'data/career.sqlite3'), demo)


app = configured_app()
