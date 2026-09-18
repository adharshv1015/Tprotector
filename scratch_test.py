import asyncio
import httpx

async def main():
    try:
        async with httpx.AsyncClient() as client:
            await client.get("https://evi.https.com")
    except Exception as e:
        print(f"Exception Type: {type(e).__name__}")
        print(f"Exception String: {str(e)}")

asyncio.run(main())
