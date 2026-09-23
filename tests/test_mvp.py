import asyncio
import copy
import json
import time
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from backend.ai import AIService
from backend.engine import ai_context, profile, recommendations
from backend.loader import load_dataset
from backend.main import create_app
from backend.models import Participation, Target

ORIGIN = {'Origin': 'http://testserver'}
HR = {'Authorization': 'Bearer hr'}


@pytest.fixture
def organizer():
    return load_dataset('data/organizer')


def test_full_dataset(organizer):
    d = organizer
    assert (len(d.employees), len(d.events), len(d.skill_catalog), len(d.history)) == (200, 40, 60, 2743)
    assert d.simulation_date == date(2026, 10, 1)
    assert sum(h.status == 'overdue' for h in d.history) == 90
    assert [e.event_id for e in d.events if e.repeatable] == ['EV_036']
    assert all(e.description and e.original_format and e.duration_hours for e in d.events)
    for employee in d.employees:
        p = profile(d, employee.employee_id)
        assert p.skill_names['SK_PYTHON'] == 'Python'
        assert all(h.status == 'completed' and employee.last_review_date < h.date <= d.simulation_date
                   for h in d.history if h.participation_id in p.applied_participation_ids)
        for item in recommendations(d, p).items:
            event = next(e for e in d.events if e.event_id == item.event_id)
            assert not event.mandatory
            assert employee.role in event.roles and employee.grade in event.grades
            assert all(p.skills.get(s, 0) >= level for s, level in event.prerequisites.items())
            assert event.format == 'self_paced' or item.facts.eligible_session_date >= d.simulation_date


def test_jury_explicit_flag_auth_and_origin(tmp_path, organizer):
    def app(enabled):
        return create_app(organizer, {'hr': {'role': 'hr'}}, str(tmp_path / 'jury.sqlite3'), jury_demo=enabled)
    c = TestClient(app(False))
    assert c.get('/auth/config').json() == {'jury_demo': False, 'employees': []}
    assert c.post('/auth/demo', json={'role': 'hr'}, headers=ORIGIN).status_code == 404
    assert c.get('/auth/me').status_code == 401
    assert c.get('/auth/me', headers=HR).json()['role'] == 'hr'
    c = TestClient(app(True))
    assert len(c.get('/auth/config').json()['employees']) == 200
    assert c.post('/auth/demo', json={'role': 'hr'}).status_code == 403
    assert c.post('/auth/demo', json={'role': 'hr'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    r = c.post('/auth/demo', json={'role': 'employee', 'employee_id': 'E0001'}, headers=ORIGIN)
    assert r.status_code == 200
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
    assert c.get('/auth/me').json() == {'role': 'employee', 'employee_id': 'E0001'}
    assert c.get('/employees/E0001').status_code == 200
    assert c.get('/employees/E0002').status_code == 403
    assert c.get('/hr/overview').status_code == 403
    assert c.post('/imports', json={}, headers=ORIGIN).status_code == 403
    assert c.post('/employees/E0002/chat', json={'message': 'Почему?'}, headers=ORIGIN).status_code == 403
    assert c.post('/employees/E0001/chat', json={'message': 'Почему?'}, headers=ORIGIN).status_code == 200
    assert c.post('/employees/E0001/chat', json={'message': 'x' * 2001}, headers=ORIGIN).status_code == 422
    assert c.post('/employees/E0001/chat', json={'message': 'Почему?'}).status_code == 403
    assert c.post('/auth/logout', headers=ORIGIN).status_code == 200
    assert c.get('/auth/me').status_code == 401
    c.post('/auth/demo', json={'role': 'hr'}, headers=ORIGIN)
    r = c.get('/hr/overview').json()
    assert len(r['event_participation']) == 40 and len(r['participation']) == 200
    assert sum(x['overdue'] for x in r['event_participation']) == 90
    for path in ['/.env', '/assets/.env', '/data/organizer.sqlite3', '/assets/../.env', '/assets/%2e%2e/.env']:
        assert c.get(path).status_code == 404
    assert c.post('/imports', content='x' * (2 * 1024 * 1024 + 1), headers=ORIGIN).status_code == 413


def test_organizer_import_atomic_deduplicated_restart(tmp_path, organizer):
    db = str(tmp_path / 'import.sqlite3')
    make = lambda: TestClient(create_app(organizer, {'hr': {'role': 'hr'}}, db))
    c = make()
    employee = json.loads(Path('data/organizer/employees.json').read_text())['employees'][0]
    employee['employee_id'] = 'JURY_NEW'
    body = {'employees': {'employees': [employee]}, 'history_csv':
            'record_id,employee_id,event_id,date,status,completion_pct\nJURY_R,JURY_NEW,EV_005,2026-09-29,completed,100\n'}
    r = c.post('/imports', json=body, headers=HR)
    assert r.status_code == 200, r.text
    assert r.json()['employees_imported'] == r.json()['history_imported'] == 1
    first = c.get('/employees/JURY_NEW', headers=HR).json()
    assert c.post('/imports', json=body, headers=HR).json()['history_imported'] == 0
    assert make().get('/employees/JURY_NEW', headers=HR).json() == first
    conflict = copy.deepcopy(body)
    conflict['employees']['employees'][0]['employee_id'] = 'SHOULD_ROLL_BACK'
    conflict['history_csv'] = conflict['history_csv'].replace('completed,100', 'declined,0')
    assert c.post('/imports', json=conflict, headers=HR).status_code == 422
    assert c.get('/employees/SHOULD_ROLL_BACK', headers=HR).status_code == 404
    changed = copy.deepcopy(body)
    changed['employees']['employees'][0]['full_name'] = 'Overwrite'
    assert c.post('/imports', json=changed, headers=HR).status_code == 422
    history_only = {'history_csv': 'record_id,employee_id,event_id,date,status\nJURY_MORE,E0001,EV_036,2026-09-30,no_show\n'}
    assert c.post('/imports', json=history_only, headers=HR).json()['history_imported'] == 1
    assert c.post('/imports', json=history_only, headers=HR).json()['history_imported'] == 0
    for value in ['bad-date', '2027-01-01']:
        bad = {'history_csv': history_only['history_csv'].replace('2026-09-30', value).replace('JURY_MORE', 'BAD')}
        assert c.post('/imports', json=bad, headers=HR).status_code == 422
    for skill, level in [('UNKNOWN_SKILL', 2), ('SK_PYTHON', 6), ('SK_PYTHON', -1)]:
        bad = copy.deepcopy(body)
        bad['employees']['employees'][0]['employee_id'] = 'BAD_EMPLOYEE'
        bad['employees']['employees'][0]['skills'][skill] = level
        bad.pop('history_csv')
        assert c.post('/imports', json=bad, headers=HR).status_code == 422
    assert c.get('/health').json()['employees_count'] == 201


def test_finish_started_without_future_session(tmp_path, dataset):
    e = dataset.events[0]
    e.format = 'scheduled'
    e.available_session_dates = []
    dataset.history = [Participation(participation_id='STARTED', employee_id='TEST_EMPLOYEE', event_id=e.event_id,
                                    status='in_progress', date='2026-09-20')]
    c = TestClient(create_app(dataset, {'hr': {'role': 'hr'}}, str(tmp_path / 'started.sqlite3')))
    r = c.post('/employees/TEST_EMPLOYEE/activities/TEST_EVENT/complete',
               json={'participation_id': 'STARTED'}, headers={**HR, 'Idempotency-Key': 'finish'})
    assert r.status_code == 200 and r.json()['profile']['skills']['TEST_DESIGN'] == 2
    assert c.post('/employees/TEST_EMPLOYEE/activities/TEST_EVENT/complete',
                  json={'participation_id': 'STARTED'}, headers={**HR, 'Idempotency-Key': 'finish'}).json() == r.json()


def test_critical_history_and_cross_role(dataset):
    d = dataset
    # Critical design gap outranks a lower non-critical skill with equal gain.
    other = d.events[0].model_copy(deep=True)
    other.event_id = 'OTHER'
    other.effects[0].skill_id = 'LOWEST'
    d.employees[0].skills['LOWEST'] = 0
    d.goals[0].requirements['LOWEST'] = 4
    d.events.append(other)
    r = recommendations(d, profile(d, 'TEST_EMPLOYEE'))
    assert r.items[0].event_id == 'TEST_EVENT'
    d.history = [Participation(participation_id=f'M{i}', employee_id='TEST_EMPLOYEE', event_id='TEST_EVENT',
                               status='no_show', date='2026-09-20') for i in range(3)]
    r = recommendations(d, profile(d, 'TEST_EMPLOYEE'))
    assert next(x for x in r.items if x.event_id == 'TEST_EVENT').facts.similar_missed == 3
    assert next(x for x in r.items if x.event_id == 'OTHER').facts.similar_missed == 0
    d.goals.append(d.goals[0].model_copy(update={'role': 'Other Role'}))
    d.employees[0].target = Target(role='Other Role', grade=d.goals[0].grade, source='employee')
    other.roles = ['Other Role']
    assert 'OTHER' not in [i.event_id for i in recommendations(d, profile(d, 'TEST_EMPLOYEE')).items]


def test_ai_success_cache_privacy_and_fallback(dataset):
    context = ai_context(dataset, 'TEST_EMPLOYEE')
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content':
            json.dumps({'explanations': [{'event_id': i.event_id, 'explanation': i.explanation} for i in context.recommendations.items]})}}]})
    service = AIService(key='secret-for-test', transport=httpx.MockTransport(handler))
    async def run():
        first = await service.explain(context)
        assert all(i.explanation_source == 'ai' for i in first.items)
        assert await service.explain(context) == first
        changed = context.model_copy(deep=True)
        changed.profile.skills['TEST_DESIGN'] = 2
        await service.explain(changed)
    asyncio.run(run())
    assert len(calls) == 2
    sent = calls[0]['messages'][1]['content']
    assert 'TEST_EMPLOYEE' not in sent and 'available_goals' not in sent and 'secret-for-test' not in sent
    for text in ['not json', '{"explanations":[{"event_id":"FOREIGN","explanation":"hello"}]}',
                 json.dumps({'explanations': [{'event_id': 'TEST_EVENT', 'explanation': 'Гарантировано повышение 999%'}]})]:
        async def bad(_):
            return text
        service = AIService(key='test')
        service.generate = bad
        assert asyncio.run(service.explain(context)) == context.recommendations


def test_ai_timeout_and_duplicates(dataset):
    context = ai_context(dataset, 'TEST_EMPLOYEE')
    async def slow(_):
        await asyncio.sleep(1)
    service = AIService(key='test', budget=0.02)
    service.generate = slow
    start = time.monotonic()
    assert asyncio.run(service.explain(context)) == context.recommendations
    assert time.monotonic() - start < 0.3
    item = context.recommendations.items[0]
    async def duplicate(_):
        return json.dumps({'explanations': [{'event_id': item.event_id, 'explanation': item.explanation}] * 2})
    service.generate = duplicate
    assert asyncio.run(service.explain(context)) == context.recommendations


def test_no_provider_keys_in_static():
    for path in Path('frontend').rglob('*'):
        if path.is_file():
            text = path.read_text(encoding='utf-8')
            assert 'Bearer demo-hr' not in text
            assert 'sk-proj-' not in text and 'nvapi-' not in text


def test_real_club_repetition_and_non_goal_gain(tmp_path, organizer, dataset):
    c = TestClient(create_app(organizer, {'hr': {'role': 'hr'}}, str(tmp_path / 'club.sqlite3')))
    before = c.get('/employees/E0001', headers=HR).json()
    endpoint = '/employees/E0001/activities/EV_036/complete'
    first = c.post(endpoint, json={'participation_id': 'CLUB_A'}, headers={**HR, 'Idempotency-Key': 'club-a'})
    assert first.status_code == 200
    replay = c.post(endpoint, json={'participation_id': 'CLUB_A'}, headers={**HR, 'Idempotency-Key': 'club-retry'})
    assert replay.json()['status'] == 'already_completed'
    second = c.post(endpoint, json={'participation_id': 'CLUB_B'}, headers={**HR, 'Idempotency-Key': 'club-b'})
    assert second.status_code == 200
    assert len(second.json()['profile']['history']) == len(before['history']) + 2
    dataset.events[0].effects[0].skill_id = 'UNRELATED'
    c = TestClient(create_app(dataset, {'hr': {'role': 'hr'}}, str(tmp_path / 'unrelated.sqlite3')))
    r = c.post('/employees/TEST_EMPLOYEE/activities/TEST_EVENT/complete', json={}, headers={**HR, 'Idempotency-Key': 'unrelated'})
    assert r.json()['profile']['skills']['UNRELATED'] == 1
    assert r.json()['profile']['progress_percent'] == profile(dataset, 'TEST_EMPLOYEE').progress_percent


def test_ai_concurrency_limit(dataset):
    context = ai_context(dataset, 'TEST_EMPLOYEE')
    service = AIService(key='fake-secret')
    active = 0
    maximum = 0
    async def generate(_):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.1)
        active -= 1
        return json.dumps({'explanations': [{'event_id': i.event_id, 'explanation': i.explanation} for i in context.recommendations.items]})
    service.generate = generate
    async def run():
        return await asyncio.gather(*(service.explain(context) for _ in range(6)))
    results = asyncio.run(run())
    assert maximum == 3
    assert sum(r.items[0].explanation_source == 'ai' for r in results) == 3
