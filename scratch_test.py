import asyncio
from httpx import AsyncClient

async def run():
    async with AsyncClient() as client:
        res = await client.get("http://localhost:8000/events?limit=50")
        print(res.status_code)
        print(res.text)

asyncio.run(run())
