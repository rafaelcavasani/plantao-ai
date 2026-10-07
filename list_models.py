import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as http:
        try:
            # Listar modelos dispon veis
            r = await http.get('https://openrouter.ai/api/v1/models', timeout=10)
            if r.status_code == 200:
                models = r.json()['data']
                # Procurar por Claude
                claude_models = [m['id'] for m in models if 'claude' in m['id'].lower() and 'sonnet' in m['id'].lower()]
                print('Modelos Claude Sonnet disponiveis:')
                for model in claude_models[:5]:
                    print(f'  - {model}')
        except Exception as e:
            print(f'Erro: {e}')

asyncio.run(test())
