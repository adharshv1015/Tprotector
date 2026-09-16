import httpx
import asyncio

async def test_api():
    try:
        async with httpx.AsyncClient() as client:
            print("Fetching APIs...")
            resp = await client.get("http://127.0.0.1:8000/apis/")
            apis = resp.json()
            print("APIs:", apis)
            if not apis:
                print("No APIs tracked.")
                return
            
            api_id = apis[0]['id']
            print(f"Triggering check for API {api_id}...")
            check_resp = await client.post(f"http://127.0.0.1:8000/apis/{api_id}/check")
            print("Status:", check_resp.status_code)
            print("Response:", check_resp.json())
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(test_api())
