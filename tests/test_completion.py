from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from backend.loader import load_dataset
from backend.main import create_app
from backend.storage import Store

TOKENS = {'token': {'role': 'employee', 'employee_id': 'DEMO_001'}, 'hr': {'role': 'hr'}}
HEADERS = {'Authorization': 'Bearer token'}
BASE = '/employees/DEMO_001'


def client_at(path):
    return TestClient(create_app(load_dataset(), TOKENS, str(path), demo=True))


def complete(client, event='DEMO_DESIGN', key='request_1', body=None):
    return client.post(f'{BASE}/activities/{event}/complete', headers={**HEADERS, 'Idempotency-Key': key}, json=body or {})


def test_full_flow_restart_and_retries(tmp_path):
    path = tmp_path / 'db.sqlite3'
    client = client_at(path)
    before = client.get(BASE, headers=HEADERS).json()
    assert before['skills']['SYSTEM_DESIGN'] == 2
    assert before['progress_percent'] == 60
    first = complete(client)
    assert first.status_code == 200
    assert first.json()['profile']['progress_percent'] == 70
    assert first.json()['profile']['skills']['SYSTEM_DESIGN'] == 3
    assert complete(client).json() == first.json()
    again = complete(client, key='different_request')
    assert again.json()['status'] == 'already_completed'
    assert again.json()['profile']['skills']['SYSTEM_DESIGN'] == 3
    restarted = client_at(path)
    assert restarted.get(BASE, headers=HEADERS).json() == first.json()['profile']
    assert complete(restarted).json() == first.json()
    assert complete(restarted, event='DEMO_PYTHON').status_code == 409


def test_repeatable_participation_identity(tmp_path):
    client = client_at(tmp_path / 'db.sqlite3')
    assert complete(client, 'DEMO_MENTOR').status_code == 422
    a = complete(client, 'DEMO_MENTOR', 'one', {'participation_id': 'mentoring_1'})
    assert a.json()['profile']['skills']['SYSTEM_DESIGN'] == 3
    b = complete(client, 'DEMO_MENTOR', 'two', {'participation_id': 'mentoring_1'})
    assert b.json()['status'] == 'already_completed'
    assert b.json()['profile']['skills']['SYSTEM_DESIGN'] == 3
    c = complete(client, 'DEMO_MENTOR', 'three', {'participation_id': 'mentoring_2'})
    assert c.json()['profile']['skills']['SYSTEM_DESIGN'] == 4


def test_concurrent_requests_award_once(tmp_path):
    path = tmp_path / 'db.sqlite3'
    client = client_at(path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: complete(client, key=f'key_{i}'), range(6)))
    assert all(r.status_code == 200 for r in results)
    assert sum(r.json()['status'] == 'completed' for r in results) == 1
    assert client.get(BASE, headers=HEADERS).json()['skills']['SYSTEM_DESIGN'] == 3
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: complete(client, 'DEMO_PYTHON', 'same'), range(6)))
    assert all(r.json() == results[0].json() for r in results)


def test_errors_do_not_write(tmp_path):
    path = tmp_path / 'db.sqlite3'
    client = client_at(path)
    before = Store(str(path), load_dataset()).snapshot().model_dump_json()
    assert complete(client, 'UNKNOWN').status_code == 404
    assert complete(client, 'DEMO_REQUIRED').status_code == 409
    assert complete(client, 'DEMO_EXPIRED').status_code == 409
    assert complete(client, body={'participation_id': 'DEMO_H04'}).status_code == 409
    assert client.post(BASE+'/activities/DEMO_DESIGN/complete', json={}).status_code == 401
    assert client.post('/employees/DEMO_002/activities/DEMO_DESIGN/complete', json={}, headers={**HEADERS,'Idempotency-Key':'foreign'}).status_code == 403
    assert complete(client, body={'gain': 5}).status_code == 422
    assert client.post(BASE+'/activities/DEMO_DESIGN/complete', json={}, headers=HEADERS).status_code == 422
    assert Store(str(path), load_dataset()).snapshot().model_dump_json() == before


def test_finish_started_and_new_goal_edge(tmp_path):
    path = tmp_path / 'db.sqlite3'
    client = client_at(path)
    r = client.post('/employees/DEMO_002/activities/DEMO_PYTHON/complete', json={'participation_id':'DEMO_H04'},
                    headers={'Authorization':'Bearer hr', 'Idempotency-Key':'finish'})
    assert r.status_code == 200
    assert r.json()['profile']['skills']['PYTHON'] == 4
    assert r.json()['participation_id'] == 'DEMO_H04'
    snapshot = Store(str(path), load_dataset()).snapshot()
    assert sum(h.participation_id == 'DEMO_H04' for h in snapshot.history) == 1
    assert next(h for h in snapshot.history if h.participation_id == 'DEMO_H04').status == 'completed'


def test_get_does_not_write_and_seed_mismatch(tmp_path):
    import pytest
    path = tmp_path / 'db.sqlite3'
    client = client_at(path)
    before = path.read_bytes()
    for _ in range(3):
        assert client.get(BASE, headers=HEADERS).status_code == 200
        assert client.get(BASE+'/recommendations', headers=HEADERS).status_code == 200
    assert before == path.read_bytes()
    changed = load_dataset()
    changed.simulation_date = changed.simulation_date.replace(day=2)
    with pytest.raises(ValueError, match='different seed'):
        Store(str(path), changed)
