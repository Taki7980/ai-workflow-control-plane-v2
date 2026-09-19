async def fetch_remote() -> str:
    return "ok"


async def parse_remote() -> str:
    return await fetch_remote()


async def start_pipeline() -> str:
    return await parse_remote()
