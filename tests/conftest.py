"""Entirely invented unit-test fixtures, never loaded into the default server."""
import pytest
from backend.models import Dataset


@pytest.fixture(autouse=True)
def no_live_provider_calls(monkeypatch):
    # Developer .env credentials must never cause network calls from regression tests.
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('NVIDIA_API_KEY', '')


@pytest.fixture
def dataset():
    return Dataset.model_validate({
        'simulation_date': '2026-10-01',
        'grade_order': ['Junior', 'Middle', 'Senior'],
        'employees': [{'employee_id': 'TEST_EMPLOYEE', 'name': 'Тестовый сотрудник (не датасет)',
                       'role': 'Test Engineer', 'grade': 'Middle', 'last_review_date': '2026-09-01',
                       'skills': {'TEST_DESIGN': 1, 'TEST_PYTHON': 5}}],
        'goals': [{'role': 'Test Engineer', 'grade': 'Senior',
                   'requirements': {'TEST_DESIGN': 4, 'TEST_PYTHON': 4}, 'critical_skills': ['TEST_DESIGN']}],
        'events': [{'event_id': 'TEST_EVENT', 'title': 'Тестовый практикум', 'category': 'workshop',
                    'mandatory': False, 'repeatable': False, 'roles': ['Test Engineer'], 'grades': ['Middle'],
                    'prerequisites': {}, 'format': 'self_paced', 'available_session_dates': [],
                    'effects': [{'skill_id': 'TEST_DESIGN', 'gain': 1, 'max_level': 4}]}],
        'history': []})
