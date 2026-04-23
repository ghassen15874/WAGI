import json
import asyncio
import aiohttp

async def main():
    payload = {
        "prompt": "Create a simple dashboard app with authentication",
        "provider": "scraper",
        "model_id": "gemini-scraper",
        "api_key": "" # fallback to settings
    }

    url = "http://127.0.0.1:8080/api/generate"
    
    print(f"Starting generation via POST {url}...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=0) as response:
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data: '):
                        data = line[6:]
                        try:
                            parsed = json.loads(data)
                            if parsed['type'] == 'token':
                                print(parsed['content'], end='', flush=True)
                            elif parsed['type'] == 'files':
                                print("\n\n=== FILES GENERATED ===")
                                print(f"Session ID: {parsed.get('session_id')}")
                                print("Generated files:")
                                for file_path in parsed.get('files', {}).keys():
                                    print(f" - {file_path}")
                            elif parsed['type'] == 'done':
                                print("\n=== GENERATION COMPLETE ===")
                            elif parsed['type'] == 'error':
                                print("\n=== ERROR ===")
                                print(parsed['message'])
                        except json.JSONDecodeError:
                            pass
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
