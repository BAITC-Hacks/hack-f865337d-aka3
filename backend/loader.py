"""Input adapters live here; engine only sees a validated internal Dataset."""
from pathlib import Path
import csv
import io
import json
from .models import Dataset, Employee, Participation, ImportRequest

DEMO_PATH = Path(__file__).resolve().parent.parent / 'demo' / 'dataset.json'


def load_dataset(path: str | Path = DEMO_PATH) -> Dataset:
    path = Path(path)
    if path.is_dir():
        return load_organizer(path)
    return Dataset.model_validate_json(path.read_text(encoding='utf-8-sig'))


def adapt_employee(raw):
    row = dict(raw)
    if 'full_name' in row:
        row['name'] = row.pop('full_name')
        goal = row.pop('career_goal', None)
        row['target'] = dict(role=goal['target_role'], grade=goal['target_grade'], source='employee') if goal else None
    return Employee.model_validate(row)


def adapt_history(raw):
    row = dict(raw)
    if 'record_id' in row:
        row['participation_id'] = row.pop('record_id')
    for key in ('due_date', 'score', 'feedback_rating', 'completion_pct', 'assigned_by'):
        if row.get(key) == '':
            row[key] = None
    return Participation.model_validate(row)


def parse_history(text):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), strict=True)
    if not {'record_id', 'employee_id', 'event_id', 'date', 'status'} <= set(reader.fieldnames or []):
        raise ValueError('CSV: отсутствуют record_id, employee_id, event_id, date или status.')
    return [adapt_history(row) for row in reader]


def adapt_import(body):
    if not isinstance(body, dict) or set(body) - {'employees', 'history', 'history_csv', 'meta'}:
        raise ValueError('Ожидается объект employees/history или history_csv.')
    employees = body.get('employees', [])
    if isinstance(employees, dict):
        employees = employees['employees']
    history = [adapt_history(h) for h in body.get('history', [])]
    if body.get('history_csv'):
        history += parse_history(body['history_csv'])
    return ImportRequest(employees=[adapt_employee(e) for e in employees], history=history)


def load_organizer(path):
    read = lambda name: json.loads((path / name).read_text(encoding='utf-8-sig'))
    employees, events, skills = read('employees.json'), read('events.json'), read('skills.json')
    return Dataset(
        simulation_date=employees['meta']['as_of_date'],
        employees=[adapt_employee(e) for e in employees['employees']],
        events=[dict(event_id=e['event_id'], title=e['title'], category=e['type'],
                     description=e['description'], original_format=e['format'], duration_hours=e['duration_hours'],
                     mandatory=e['mandatory'], repeatable=e['event_id'] == 'EV_036',
                     roles=e['target_roles'], grades=e['target_grades'], prerequisites=e['prerequisites'],
                     format='self_paced' if e['format'] == 'self_paced' else 'scheduled',
                     available_session_dates=e['upcoming_sessions'], effects=e['develops_skills']) for e in events['events']],
        history=parse_history((path / 'activity_history.csv').read_text(encoding='utf-8-sig')),
        goals=[dict(role=g['role'], grade=g['grade'], requirements=g['required_skills'],
                    critical_skills=g['critical_skills']) for g in skills['role_profiles']],
        grade_order=['Junior', 'Middle', 'Senior', 'Lead'], skill_catalog=skills['skills'])
