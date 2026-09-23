from datetime import date
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend.engine import ai_context, apply_effects, profile, recommendations
from backend.main import create_app
from backend.models import Dataset, Participation

TOKENS = {'test-token': {'role': 'employee', 'employee_id': 'TEST_EMPLOYEE'}, 'hr-test': {'role': 'hr'}}
HEADERS = {'Authorization': 'Bearer test-token'}


def history(status='completed', day='2026-09-02', pid='TEST_PARTICIPATION'):
    return Participation(participation_id=pid, employee_id='TEST_EMPLOYEE', event_id='TEST_EVENT', status=status, date=day)


def test_health_without_data():
    client = TestClient(create_app(tokens=TOKENS))
    assert client.get('/health').json()['dataset_loaded'] is False
    assert client.get('/employees/TEST_EMPLOYEE', headers=HEADERS).status_code == 503


def test_profile_and_auth(dataset):
    client = TestClient(create_app(dataset, TOKENS))
    assert client.get('/employees/TEST_EMPLOYEE').status_code == 401
    assert client.get('/employees/OTHER', headers=HEADERS).status_code == 403
    assert client.get('/employees/OTHER', headers={'Authorization': 'Bearer hr-test'}).status_code == 404
    result = client.get('/employees/TEST_EMPLOYEE', headers=HEADERS)
    assert result.status_code == 200
    assert result.json()['progress_percent'] == 62.5
    assert result.json()['target']['source'] == 'system'
    assert client.get('/employees/TEST_EMPLOYEE/recommendations', headers=HEADERS).json()['items'][0]['progress_after'] == 75


@pytest.mark.parametrize('status', ['declined', 'dropped', 'no_show', 'in_progress'])
def test_no_gain_for_uncompleted(dataset, status):
    dataset.history = [history(status)]
    assert profile(dataset, 'TEST_EMPLOYEE').skills['TEST_DESIGN'] == 1


def test_review_boundary_and_future(dataset):
    dataset.history = [history(day='2026-09-01', pid='a'), history(day='2026-09-02', pid='b'), history(day='2026-10-02', pid='c')]
    before = dataset.model_dump_json()
    p = profile(dataset, 'TEST_EMPLOYEE')
    assert p.skills['TEST_DESIGN'] == 2
    assert p.applied_participation_ids == ['b']
    assert profile(dataset, 'TEST_EMPLOYEE') == p
    assert dataset.model_dump_json() == before


def test_caps_never_reduce_and_missing_zero(dataset):
    e = dataset.events[0]
    assert apply_effects({'TEST_DESIGN': 5}, e)['TEST_DESIGN'] == 5
    assert apply_effects({}, e)['TEST_DESIGN'] == 1


@pytest.mark.parametrize('blocked', ['mandatory', 'roles', 'grades', 'prerequisites', 'session', 'completed', 'started'])
def test_availability(dataset, blocked):
    e = dataset.events[0]
    if blocked == 'mandatory': e.mandatory = True
    if blocked == 'roles': e.roles = ['Other']
    if blocked == 'grades': e.grades = ['Junior']
    if blocked == 'prerequisites': e.prerequisites = {'MISSING': 1}
    if blocked == 'session':
        e.format = 'scheduled'
        e.available_session_dates = [date(2026, 9, 30)]
    if blocked == 'completed': dataset.history = [history()]
    if blocked == 'started': dataset.history = [history('in_progress')]
    r = recommendations(dataset, profile(dataset, 'TEST_EMPLOYEE'))
    assert r.items == []
    assert r.empty_reason == 'no_eligible_activities'


def test_repeatable_and_independent_effects(dataset):
    dataset.history = [history()]
    dataset.events[0].repeatable = True
    dataset.events.append(dataset.events[0].model_copy(update={'event_id': 'TEST_EVENT_2'}))
    r = recommendations(dataset, profile(dataset, 'TEST_EMPLOYEE'))
    assert len(r.items) == 2
    assert all(item.progress_before == 75 and item.progress_after == 87.5 for item in r.items)


def test_no_next_grade(dataset):
    dataset.employees[0].grade = 'Senior'
    p = profile(dataset, 'TEST_EMPLOYEE')
    assert p.target is None and p.progress_percent is None
    assert recommendations(dataset, p).empty_reason == 'target_required'


def test_duplicate_participation_rejected(dataset):
    raw = dataset.model_dump()
    raw['history'] = [history().model_dump(), history().model_dump()]
    with pytest.raises(ValidationError): Dataset.model_validate(raw)


def test_history_factor_and_ai_context(dataset):
    dataset.history = [history('no_show')]
    context = ai_context(dataset, 'TEST_EMPLOYEE')
    item = context.recommendations.items[0]
    assert item.facts.history_factor == -0.1
    assert item.facts.weighted_gap_reduction == 2
    assert item.explanation_source == 'fallback'
    assert item.facts.similar_missed == 1


def test_chronological_application(dataset):
    second = dataset.events[0].model_copy(deep=True)
    second.event_id = 'TEST_SECOND'
    second.effects[0].gain = 3
    second.effects[0].max_level = 5
    dataset.events[0].effects[0].max_level = 2
    dataset.events.append(second)
    later = history(day='2026-09-03', pid='a')
    later.event_id = 'TEST_SECOND'
    dataset.history = [later, history(day='2026-09-02', pid='b')]
    assert profile(dataset, 'TEST_EMPLOYEE').skills['TEST_DESIGN'] == 5
