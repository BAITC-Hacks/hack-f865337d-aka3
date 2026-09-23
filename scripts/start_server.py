"""Local Windows launcher; preserves the existing database and environment settings."""
import os
from pathlib import Path
import socket
import sys


def main():
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    sys.path.insert(0, str(root))
    try:
        import fastapi  # noqa: F401
        import pydantic  # noqa: F401
        import uvicorn
    except ImportError:
        print('ERROR: Missing project dependencies. Run:', flush=True)
        print(r'.venv\Scripts\python.exe -m pip install -r requirements.txt', flush=True)
        return 1

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('127.0.0.1', 8000))
    except OSError:
        print('ERROR: Cannot bind 127.0.0.1:8000. The port is occupied or access is denied.', flush=True)
        print('No existing process was stopped. Check http://127.0.0.1:8000/health', flush=True)
        return 1

    print('Career Quest: http://127.0.0.1:8000/', flush=True)
    print('Frontend and API use this single server. Wait for Application startup complete.', flush=True)
    print('Keep this terminal open. Press Ctrl+C to stop.', flush=True)
    print('Existing database and CAREER_QUEST settings are preserved.', flush=True)
    try:
        uvicorn.run('backend.main:app', host='127.0.0.1', port=8000)
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        # Do not dump environment values or validation inputs containing credentials.
        print(f'ERROR: Server startup failed ({type(error).__name__}).', flush=True)
        print('Check data paths, CAREER_QUEST settings and database/seed compatibility. Do not delete the database.', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
