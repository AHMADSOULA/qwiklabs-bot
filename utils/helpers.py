import random
import asyncio
import re


def random_delay(min_s=1.0, max_s=2.5):
    return random.uniform(min_s, max_s)


async def human_delay(min_s=1.0, max_s=2.5):
    await asyncio.sleep(random_delay(min_s, max_s))


async def human_move(page, x=None, y=None):
    vp = page.viewport_size or {"width": 1920, "height": 1080}
    x = x or random.randint(100, vp["width"] - 100)
    y = y or random.randint(100, vp["height"] - 100)
    await page.mouse.move(x, y, steps=random.randint(8, 20))
    await asyncio.sleep(random.uniform(0.1, 0.3))


def extract_urls(text: str):
    pattern = r'https?://[^\s<>"]+'
    return re.findall(pattern, text)
