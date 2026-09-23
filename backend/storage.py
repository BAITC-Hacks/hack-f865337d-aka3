"""SQLite snapshot + transactional completion; source JSON is never modified."""
from contextlib import contextmanager
import hashlib
import sqlite3
from pathlib import Path
from uuid import uuid4
from .engine import profile, recommendations, eligible
from .models import CompletionRequest, CompletionResponse, Dataset, Participation, Target


class CompletionError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status


class Store:
    def __init__(self, path: str, seed: Dataset):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK(id=1), seed_hash TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    employee_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    payload TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(employee_id, request_key));
            ''')
            encoded = seed.model_dump_json()
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            conn.execute('INSERT OR IGNORE INTO snapshot VALUES (1, ?, ?)', (fingerprint, encoded))
            if conn.execute('SELECT seed_hash FROM snapshot WHERE id=1').fetchone()[0] != fingerprint:
                raise ValueError('Database belongs to a different seed. Set CAREER_QUEST_DB to a new file.')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def read(conn):
        return Dataset.model_validate_json(conn.execute('SELECT body FROM snapshot WHERE id=1').fetchone()[0])

    def snapshot(self):
        with self.connect() as conn:
            return self.read(conn)

    def complete(self, employee_id: str, event_id: str, request: CompletionRequest, key: str):
        payload = event_id + ':' + request.model_dump_json()
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            saved = conn.execute('SELECT payload,response FROM requests WHERE employee_id=? AND request_key=?',
                                 (employee_id, key)).fetchone()
            if saved:
                if saved[0] != payload:
                    raise CompletionError('idempotency_conflict', 'Этот ключ уже использован для другого запроса.')
                return CompletionResponse.model_validate_json(saved[1])
            data = self.read(conn)
            event = next((e for e in data.events if e.event_id == event_id), None)
            if event is None:
                raise CompletionError('event_not_found', 'Активность не найдена.', 404)
            if event.repeatable and not request.participation_id:
                raise CompletionError('participation_required', 'Для повторяемой активности требуется participation_id.', 422)
            existing = next((h for h in data.history if request.participation_id and h.participation_id == request.participation_id), None)
            if existing and (existing.employee_id != employee_id or existing.event_id != event_id):
                raise CompletionError('participation_conflict', 'Идентификатор участия уже занят.')
            prior = next((h for h in data.history if h.employee_id == employee_id and h.event_id == event_id
                          and h.status == 'completed' and h.date <= data.simulation_date), None)
            if existing and existing.date > data.simulation_date:
                raise CompletionError('participation_conflict', 'Участие относится к будущей дате.')
            done = existing if existing and existing.status == 'completed' else prior if not event.repeatable else None
            if done:
                status, pid = 'already_completed', done.participation_id
            else:
                p = profile(data, employee_id)
                # Starting an available activity or finishing a current participation is allowed.
                active = [h for h in data.history if h.employee_id == employee_id and h.event_id == event_id
                          and h.status == 'in_progress' and h.date <= data.simulation_date]
                if active and request.participation_id and all(h.participation_id != request.participation_id for h in active):
                    raise CompletionError('participation_in_progress', 'Завершите уже начатое участие с его participation_id.')
                if existing and (existing.status != 'in_progress' or existing.date > data.simulation_date):
                    raise CompletionError('participation_conflict', 'Это участие нельзя завершить в деморежиме.')
                if not eligible(data, p, event, allow_started=True):
                    raise CompletionError('activity_unavailable', 'Активность недоступна для этого сотрудника.')
                employee = next(e for e in data.employees if e.employee_id == employee_id)
                if employee.last_review_date >= data.simulation_date:
                    raise CompletionError('review_date_conflict', 'Дата выполнения должна быть позже последней оценки.')
                participation = existing or (active[0] if active else None)
                pid = participation.participation_id if participation else request.participation_id or ('demo_' + uuid4().hex)
                if participation:
                    data.history.remove(participation)
                data.history.append(Participation(participation_id=pid, employee_id=employee_id,
                                    event_id=event_id, status='completed', date=data.simulation_date))
                # Full model validation before committing persisted state.
                data = Dataset.model_validate(data.model_dump())
                conn.execute('UPDATE snapshot SET body=? WHERE id=1', (data.model_dump_json(),))
                status = 'completed'
            updated = profile(data, employee_id)
            response = CompletionResponse(status=status, participation_id=pid, profile=updated,
                                          recommendations=recommendations(data, updated))
            conn.execute('INSERT INTO requests VALUES (?, ?, ?, ?)',
                         (employee_id, key, payload, response.model_dump_json()))
            return response

    def import_profiles(self, request):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            data = self.read(conn)
            # Append only: never overwrite reviews, history or idempotency snapshots.
            candidate = data.model_dump()
            candidate['employees'] += [e.model_dump() for e in request.employees]
            candidate['history'] += [h.model_dump() for h in request.history]
            new_ids = {e.employee_id for e in request.employees}
            if any(h.employee_id not in new_ids for h in request.history):
                raise CompletionError('import_conflict', 'История должна относиться к новым профилям.', 422)
            data = Dataset.model_validate(candidate)
            conn.execute('UPDATE snapshot SET body=? WHERE id=1', (data.model_dump_json(),))
            return {'employee_ids': [e.employee_id for e in request.employees],
                    'employees_imported': len(request.employees), 'history_imported': len(request.history)}

    def set_goal(self, employee_id, request):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            data = self.read(conn)
            if not any(g.role == request.role and g.grade == request.grade for g in data.goals):
                raise CompletionError('unknown_goal', 'Такая цель отсутствует в справочнике.', 422)
            employee = next(e for e in data.employees if e.employee_id == employee_id)
            employee.target = Target(role=request.role, grade=request.grade, source='employee')
            data = Dataset.model_validate(data.model_dump())
            conn.execute('UPDATE snapshot SET body=? WHERE id=1', (data.model_dump_json(),))
            return profile(data, employee_id)
