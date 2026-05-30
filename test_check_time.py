import asyncio
from utils.checkers import check_site
import json

async def main():
    r = await check_site("sidelineprints.com")
    print(json.dumps(r, indent=2))

asyncio.run(main())
