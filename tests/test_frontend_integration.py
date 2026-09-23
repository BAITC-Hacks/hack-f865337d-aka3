import json
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from backend.loader import load_dataset
from backend.main import create_app
from backend.models import Participation

TOKENS = {'employee': {'role': 'employee', 'employee_id': 'DEMO_001'}, 'hr': {'role': 'hr'}}
EMP = {'Authorization': 'Bearer employee'}
HR = {'Authorization': 'Bearer hr'}


def client_at(tmp_path, data=None):
    return TestClient(create_app(data or load_dataset(), TOKENS, str(tmp_path / 'integration.sqlite3'), demo=True))


def test_import_atomic_authorized_and_visible_after_restart(tmp_path):
    client = client_at(tmp_path)
    body = json.loads(Path('frontend/import-example.json').read_text(encoding='utf-8'))
    assert client.post('/imports', json=body).status_code == 401
    assert client.post('/imports', json=body, headers=EMP).status_code == 403
    assert client.get('/hr/overview', headers=EMP).status_code == 403
    assert client.get('/hr/overview').status_code == 401
    response = client.post('/imports', json=body, headers=HR)
    assert response.status_code == 200
    assert response.json()['history_imported'] == 1
    imported = client.get('/employees/IMPORTED_001', headers=HR).json()
    assert imported['skills']['SYSTEM_DESIGN'] == 2
    assert imported['history'][0]['participation_id'] == 'IMPORTED_HISTORY_001'
    assert client.get('/health').json()['employees_count'] == 4
    assert client.get('/hr/overview', headers=HR).json()['employees_count'] == 4
    assert client.get('/employees/IMPORTED_001', headers=EMP).status_code == 403
    assert client_at(tmp_path).get('/employees/IMPORTED_001', headers=HR).json() == imported
    replay = client.post('/imports', json=body, headers=HR)
    assert replay.status_code == 200
    assert replay.json()['employees_imported'] == replay.json()['history_imported'] == 0
    assert client.get('/employees/IMPORTED_001', headers=HR).json() == imported
    assert client.get('/health').json()['employees_count'] == 4
    body['employees'][0]['employee_id'] = 'INVALID_NEW'
    body['history'][0]['employee_id'] = 'INVALID_NEW'
    body['history'][0]['event_id'] = 'UNKNOWN'
    assert client.post('/imports', json=body, headers=HR).status_code == 422
    assert client.get('/employees/INVALID_NEW', headers=HR).status_code == 404
    assert client.post('/imports', json={'employees': [], 'history': []}, headers=HR).status_code == 422
    assert client.post('/imports', content='{invalid', headers={**HR, 'Content-Type': 'application/json'}).status_code == 422


def test_goal_and_hr_follow_saved_completion(tmp_path):
    client = client_at(tmp_path)
    p = client.get('/employees/DEMO_003', headers=HR).json()
    assert p['target'] is None and p['progress_percent'] is None
    assert client.get('/employees/DEMO_003/recommendations', headers=HR).json()['empty_reason'] == 'target_required'
    body = {'role': 'Backend Engineer', 'grade': 'Senior'}
    assert client.post('/employees/DEMO_003/goal', json=body, headers=EMP).status_code == 403
    assert client.post('/employees/DEMO_003/goal', json=body, headers=HR).json()['target_status'] == 'selected'
    assert client_at(tmp_path).get('/employees/DEMO_003', headers=HR).json()['target']['grade'] == 'Senior'
    assert client.post('/employees/DEMO_003/goal', json={'role': 'Unknown', 'grade': 'X'}, headers=HR).status_code == 422
    before = client.get('/hr/overview', headers=HR).json()
    response = client.post('/employees/DEMO_001/activities/DEMO_DESIGN/complete', json={}, headers={**EMP, 'Idempotency-Key':'design'})
    assert response.status_code == 200
    after = client.get('/hr/overview', headers=HR).json()
    count = lambda data: next(x['completed'] for x in data['participation'] if x['employee_id'] == 'DEMO_001')
    assert count(after) == count(before) + 1
    assert client.post('/employees/DEMO_001/goal', json={'role':'Backend Engineer','grade':'Middle'}, headers=EMP).status_code == 200
    assert client.get('/employees/DEMO_001/recommendations', headers=EMP).json()['empty_reason'] == 'target_covered'
    # A replay remains historical; GET reflects the newly selected goal.
    replay = client.post('/employees/DEMO_001/activities/DEMO_DESIGN/complete', json={}, headers={**EMP,'Idempotency-Key':'design'})
    assert replay.json()['profile']['target']['grade'] == 'Senior'
    assert client.get('/employees/DEMO_001', headers=EMP).json()['target']['grade'] == 'Middle'


def test_future_completion_and_review_boundary(tmp_path):
    data = load_dataset()
    data.history.append(Participation(participation_id='future', employee_id='DEMO_001', event_id='DEMO_DESIGN', status='completed', date=data.simulation_date + timedelta(days=1)))
    client = client_at(tmp_path, data)
    assert 'DEMO_DESIGN' in [x['event_id'] for x in client.get('/employees/DEMO_001/recommendations', headers=EMP).json()['items']]
    result = client.post('/employees/DEMO_001/activities/DEMO_DESIGN/complete', json={}, headers={**EMP,'Idempotency-Key':'now'})
    assert result.json()['status'] == 'completed'
    assert result.json()['profile']['progress_percent'] == 70
    assert client.post('/employees/DEMO_001/activities/DEMO_DESIGN/complete', json={'participation_id':'future'}, headers={**EMP,'Idempotency-Key':'future'}).status_code == 409


def test_review_date_does_not_reapply_historical_skills(tmp_path):
    data = load_dataset()
    data.employees[0].last_review_date = data.simulation_date
    data.history.append(Participation(participation_id='review-day',employee_id='DEMO_001',event_id='DEMO_INTRO',status='completed',date=data.simulation_date))
    client = client_at(tmp_path, data)
    before = client.get('/employees/DEMO_001', headers=EMP).json()
    assert before['completion_available'] is False and before['completion_message']
    assert before['skills']['SYSTEM_DESIGN'] == 1
    result = client.post('/employees/DEMO_001/activities/DEMO_DESIGN/complete',json={},headers={**EMP,'Idempotency-Key':'review'})
    assert result.status_code == 409 and result.json()['detail']['code'] == 'review_date_conflict'
    assert client.get('/employees/DEMO_001', headers=EMP).json() == before


def test_metadata_history_static_and_cors(tmp_path):
    client = client_at(tmp_path)
    recs = client.get('/employees/DEMO_001/recommendations', headers=EMP).json()
    assert all('repeatable' in item and 'format' in item for item in recs['items'])
    p = client.get('/employees/DEMO_002', headers=HR).json()
    assert any(h['status'] == 'in_progress' and h['participation_id'] == 'DEMO_H04' for h in p['history'])
    assert client.get('/').status_code == 200
    assert client.get('/assets/app.js').headers['content-type'].split(';')[0] in ('text/javascript', 'application/javascript')
    for origin in ['http://localhost:5173', 'http://127.0.0.1:5173']:
        response = client.options('/employees/DEMO_001', headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'Authorization,Idempotency-Key,Content-Type'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == origin
