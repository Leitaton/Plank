import asyncio
from config import CHECKER_API_URL
import aiohttp

async def test_api():
    async with aiohttp.ClientSession() as session:
        # test 1: /check with max_price
        async with session.get(f"{CHECKER_API_URL}/check", params={"site": "https://kyliebaby.com", "max_price": 8}) as r:
            print("With max_price:", r.status, await r.text())
        
        # test 2: /shopify with test card
        async with session.get(f"{CHECKER_API_URL}/shopify", params={"cc": "4111111111111111|12|2030|123", "site": "https://kyliebaby.com", "max_price": 8}) as r:
            print("Shopify check:", r.status, await r.text())

asyncio.run(test_api())
