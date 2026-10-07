import asyncio
import httpx
from core.config import settings

async def test_model(model_name):
    async with httpx.AsyncClient() as http:
        data = {'model': model_name, 'messages': [{'role': 'user', 'content': 'test'}], 'temperature': 0}
        headers = {'Authorization': f'Bearer {settings.openrouter_api_key}'}
        try:
            r = await http.post('https://openrouter.ai/api/v1/chat/completions', json=data, headers=headers, timeout=10)
            if r.status_code == 200:
                print(f'✓ {model_name}: OK')
                return True
            else:
                body = r.json()
                print(f'✗ {model_name}: {body["error"]["message"][:80]}')
                return False
        except Exception as e:
            print(f'✗ {model_name}: {e}')
            return False

async def test():
    models = [
        'anthropic/claude-opus-4-1',
        'anthropic/claude-3-opus',
        'anthropic/claude-sonnet-4-20250514'
    ]
    for model in models:
        if await test_model(model):
            print(f'\nUsar: {model}')
            break

asyncio.run(test())
