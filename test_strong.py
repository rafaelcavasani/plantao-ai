import asyncio
import httpx
from core.config import settings

async def test():
    print('Testando modelo Strong...')
    async with httpx.AsyncClient() as http:
        data = {
            'model': 'anthropic/claude-3.5-sonnet',
            'messages': [{'role': 'user', 'content': 'Teste'}],
            'temperature': 0
        }
        headers = {'Authorization': f'Bearer {settings.openrouter_api_key}'}
        try:
            r = await http.post('https://openrouter.ai/api/v1/chat/completions', json=data, headers=headers, timeout=15)
            print(f'Status: {r.status_code}')
            if r.status_code != 200:
                body = r.json()
                print(f'Erro: {body["error"]["message"]}')
        except Exception as e:
            print(f'Erro: {type(e).__name__}: {e}')

asyncio.run(test())
