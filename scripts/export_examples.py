"""Run: .venv/bin/python -m scripts.export_examples; uses an isolated temporary DB."""
import json
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from backend.engine import ai_context
from backend.loader import load_dataset
from backend.main import create_app

out = Path('docs/examples')
out.mkdir(parents=True, exist_ok=True)

def save(name, data):
    (out / (name + '.demo.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

with tempfile.TemporaryDirectory() as temp:
    app = create_app(load_dataset(), {'demo-employee-1': {'role':'employee', 'employee_id':'DEMO_001'}, 'demo-hr': {'role':'hr'}}, temp+'/demo.sqlite3', demo=True)
    client = TestClient(app)
    headers = {'Authorization': 'Bearer demo-employee-1'}
    base = '/employees/DEMO_001'
    save('profile', client.get(base, headers=headers).json())
    save('recommendations', client.get(base+'/recommendations', headers=headers).json())
    save('ai-context', ai_context(load_dataset(), 'DEMO_001').model_dump(mode='json'))
    response = client.post(base+'/activities/DEMO_DESIGN/complete', headers={**headers,'Idempotency-Key':'example-1'}, json={'participation_id':'demo-design-example'})
    assert response.status_code == 200
    save('completion', response.json())
    save('profile-after', client.get(base, headers=headers).json())
    save('recommendations-after', client.get(base+'/recommendations', headers=headers).json())
    hr_headers = {'Authorization': 'Bearer demo-hr'}
    save('hr-overview', client.get('/hr/overview', headers=hr_headers).json())
    imported = client.post('/imports', json=json.loads(Path('frontend/import-example.json').read_text(encoding='utf-8')), headers=hr_headers)
    assert imported.status_code == 200
    save('import-result', imported.json())
    save('profile-imported', client.get('/employees/IMPORTED_001', headers=hr_headers).json())
    Path('docs/openapi.json').write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
