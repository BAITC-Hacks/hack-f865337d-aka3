"""One live provider call; prints no credentials, prompts or provider response body."""
import asyncio
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from backend.ai import AIService
from backend.engine import ai_context
from backend.loader import load_dataset


async def main():
    ai = AIService()
    if not ai.key:
        print('AI key is not configured. Set OPENAI_API_KEY in the server .env.')
        return 1
    context = ai_context(load_dataset(ROOT / 'data' / 'organizer'), 'E0001')
    start = time.monotonic()
    try:
        async with asyncio.timeout(8):
            raw = await ai.generate(context)
    except Exception as error:
        status = getattr(getattr(error, 'response', None), 'status_code', None)
        print(f'Provider call failed: {type(error).__name__}; HTTP status={status}. No secrets logged.')
        return 1
    # Validate that very same response through the production acceptance path.
    async def same_response(_):
        return raw
    ai.generate = same_response
    result = await ai.explain(context)
    accepted = all(i.explanation_source == 'ai' for i in result.items)
    print(f'provider={ai.provider}; model={ai.model}; live_response=True; accepted={accepted}; elapsed={time.monotonic()-start:.2f}s')
    return 0 if accepted else 2


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
