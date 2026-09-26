from utils.logger import get_logger
from utils.helpers import human_delay, human_move
from utils.screenshot import take_screenshot

log = get_logger("CloudConsole")


class CloudConsole:
    def __init__(self, context):
        self.context = context

    async def login(self, username: str, password: str):
        page = await self.context.new_page()
        log.info("تسجيل الدخول إلى Cloud Console...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_01_loaded")

        try:
            # Email
            await page.wait_for_selector('input[type="email"]', timeout=30000)
            await human_move(page)
            await page.fill('input[type="email"]', username)
            await human_delay(0.5, 1.5)
            await page.click('#identifierNext')
            await human_delay(2, 4)

            # Password
            await page.wait_for_selector('input[type="password"]', timeout=30000)
            await human_move(page)
            await page.fill('input[type="password"]', password)
            await human_delay(0.5, 1.5)
            await page.click('#passwordNext')
            await human_delay(4, 7)

            log.info(f"URL الحالي: {page.url}")
            return page
        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            raise
