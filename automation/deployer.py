"""
automation/deployer.py
كل خطوات Cloud Run — بلا تصوير لتوفير الذاكرة
"""
import asyncio
import re
from urllib.parse import urlparse, parse_qs

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import expect

from utils.logger import get_logger

log = get_logger("Deployer")


def extract_project_id(url: str) -> str:
    m = re.search(r'(qwiklabs-gcp-[\w-]+)', url or "")
    return m.group(1) if m else None


def extract_domain_from_service_url(service_url: str) -> str:
    s = (service_url or "").strip()
    if s.startswith("http://") or s.startswith("https://"):
        return urlparse(s).netloc.strip()
    return s.replace("http://", "").replace("https://", "").split("/")[0].strip()


class CloudRunDeployer:
    def __init__(self, page):
        self.page = page

    # ==================== STEP 1: TOS الأولى ====================

    async def step1_welcome_screen(self):
        log.info("🚀 step1: بدء")
        page = self.page

        try:
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2500)

            is_tos = await page.evaluate("""
                () => {
                    const url = window.location.href.toLowerCase();
                    if (url.includes('workspacetermsofservice') || url.includes('speedbump')) return true;
                    const text = (document.body.innerText || '').toLowerCase();
                    if (text.includes('welcome to your new account')) return true;
                    for (const el of document.querySelectorAll('button, [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (t.includes('i understand')) return true;
                    }
                    return false;
                }
            """)

            if not is_tos:
                log.info("ℹ️ ماشي TOS")
                return

            target = await page.evaluate("""
                () => {
                    const kws = ['i understand', 'agree and continue', 'accept'];
                    for (const el of document.querySelectorAll('button, a, [role="button"], input[type="submit"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        for (const kw of kws) {
                            if (t.includes(kw)) {
                                const rect = el.getBoundingClientRect();
                                return {
                                    text: (el.innerText || el.value || '').trim(),
                                    x: Math.round(rect.x + rect.width / 2),
                                    y: Math.round(rect.y + rect.height / 2),
                                };
                            }
                        }
                    }
                    return null;
                }
            """)

            if not target:
                log.warning("⚠️ ما لقيناش الزر")
                return

            log.info(f"🎯 '{target['text']}' @({target['x']},{target['y']})")

            try:
                await page.evaluate(f"""
                    () => {{
                        const el = document.elementFromPoint({target['x']}, {target['y']});
                        if (el) el.scrollIntoView({{block: 'center', behavior: 'instant'}});
                    }}
                """)
                await page.wait_for_timeout(800)

                target2 = await page.evaluate("""
                    () => {
                        const kws = ['i understand', 'agree and continue', 'accept'];
                        for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                            if (el.offsetParent === null || el.disabled) continue;
                            const t = (el.innerText || '').trim().toLowerCase();
                            for (const kw of kws) {
                                if (t.includes(kw)) {
                                    const rect = el.getBoundingClientRect();
                                    return {
                                        x: Math.round(rect.x + rect.width / 2),
                                        y: Math.round(rect.y + rect.height / 2),
                                    };
                                }
                            }
                        }
                        return null;
                    }
                """)
                if target2:
                    target['x'] = target2['x']
                    target['y'] = target2['y']

                await page.mouse.move(target['x'] - 150, target['y'] - 80, steps=12)
                await page.wait_for_timeout(300)
                await page.mouse.move(target['x'] - 50, target['y'] - 20, steps=10)
                await page.wait_for_timeout(300)
                await page.mouse.move(target['x'], target['y'], steps=8)
                await page.wait_for_timeout(500)
                await page.mouse.down()
                await page.wait_for_timeout(120)
                await page.mouse.up()
                log.info("✅ mouse click")
            except Exception as e:
                log.warning(f"❌ mouse: {e}")
                try:
                    await page.get_by_role("button", name="I understand").click(timeout=5000)
                except Exception:
                    pass

            for i in range(20):
                await page.wait_for_timeout(2000)
                try:
                    gone = await page.evaluate("""
                        () => {
                            for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                                if (el.offsetParent === null || el.disabled) continue;
                                const t = (el.innerText || '').trim().toLowerCase();
                                if (t.includes('i understand') || t.includes('agree and continue')) return false;
                            }
                            return true;
                        }
                    """)
                    if gone:
                        log.info(f"✅ TOS اختفت ~{(i+1)*2}s")
                        break
                except Exception:
                    log.info(f"⏳ {i+1}")
            log.info("✅ step1 انتهى")
        except Exception as e:
            log.warning(f"❌ step1: {e}")

    # ==================== STEP 2: Terms Dialog ====================

    async def step2_terms_dialog(self):
        log.info("🚀 step2: بدء")
        page = self.page

        try:
            has_dialog = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('[role="dialog"], [role="alertdialog"], .modal, md-dialog')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').toLowerCase();
                        if (t.includes('terms of service') && (t.includes('agree') || t.includes('i agree'))) {
                            return true;
                        }
                    }
                    return false;
                }
            """)
        except Exception as e:
            log.warning(f"⚠️ page crash: {e}")
            try:
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
            except Exception:
                pass
            return

        if not has_dialog:
            log.info("ℹ️ ما كاينش Dialog")
            return

        log.info("📋 لقينا Dialog")

        # checkbox
        try:
            checkbox_info = await page.evaluate("""
                () => {
                    const containers = [
                        ...document.querySelectorAll('[role="dialog"], [role="alertdialog"], .modal, md-dialog'),
                        document.body
                    ];
                    for (const container of containers) {
                        for (const el of container.querySelectorAll('input[type="checkbox"], [role="checkbox"], mat-checkbox')) {
                            if (el.offsetParent === null) continue;
                            const parent = el.closest('label, div, mat-checkbox') || el.parentElement;
                            const txt = (parent?.innerText || '').toLowerCase();
                            if (txt.includes('i agree') || txt.includes('terms of service') || txt.includes('cloud platform')) {
                                const rect = el.getBoundingClientRect();
                                if (rect.width === 0 || rect.height === 0) continue;
                                return {
                                    x: Math.round(rect.x + rect.width / 2),
                                    y: Math.round(rect.y + rect.height / 2),
                                    checked: el.checked || el.getAttribute('aria-checked') === 'true',
                                };
                            }
                        }
                    }
                    return null;
                }
            """)
        except Exception as e:
            log.warning(f"⚠️ checkbox evaluate: {e}")
            checkbox_info = None

        if checkbox_info and not checkbox_info['checked']:
            log.info(f"📋 checkbox @({checkbox_info['x']},{checkbox_info['y']})")
            try:
                await page.mouse.move(checkbox_info['x'] - 40, checkbox_info['y'] - 40, steps=10)
                await page.wait_for_timeout(300)
                await page.mouse.move(checkbox_info['x'], checkbox_info['y'], steps=8)
                await page.wait_for_timeout(300)
                await page.mouse.down()
                await page.wait_for_timeout(120)
                await page.mouse.up()
                log.info("✅ checkbox mouse")
                await page.wait_for_timeout(2000)

                checked_now = await page.evaluate("""
                    () => {
                        for (const el of document.querySelectorAll('input[type="checkbox"], [role="checkbox"], mat-checkbox')) {
                            if (el.offsetParent === null) continue;
                            const parent = el.closest('label, div, mat-checkbox') || el.parentElement;
                            const txt = (parent?.innerText || '').toLowerCase();
                            if (txt.includes('i agree') || txt.includes('terms of service')) {
                                return el.checked || el.getAttribute('aria-checked') === 'true';
                            }
                        }
                        return false;
                    }
                """)
                if not checked_now:
                    for sel in ['mat-checkbox', '[role="dialog"] input[type="checkbox"]', '[role="dialog"] [role="checkbox"]']:
                        try:
                            el = page.locator(sel).first
                            if await el.count() > 0 and await el.is_visible():
                                await el.click(force=True, timeout=3000)
                                log.info(f"✅ Playwright checkbox")
                                break
                        except Exception:
                            continue
                    await page.wait_for_timeout(1500)
            except Exception as e:
                log.warning(f"❌ checkbox: {e}")

        await page.wait_for_timeout(1500)

        # Agree button
        try:
            agree_target = await page.evaluate("""
                () => {
                    const kws = ['agree and continue', 'i agree', 'accept', 'agree'];
                    for (const el of document.querySelectorAll('button, [role="button"], input[type="submit"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        for (const kw of kws) {
                            if (t === kw || t.includes(kw)) {
                                const rect = el.getBoundingClientRect();
                                if (rect.width === 0 || rect.height === 0) continue;
                                const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                                return {
                                    text: (el.innerText || el.value || '').trim(),
                                    x: Math.round(rect.x + rect.width / 2),
                                    y: Math.round(rect.y + rect.height / 2),
                                    disabled: disabled,
                                };
                            }
                        }
                    }
                    return null;
                }
            """)
        except Exception as e:
            log.warning(f"⚠️ agree evaluate: {e}")
            return

        if not agree_target:
            log.warning("⚠️ ما لقيناش Agree")
            return

        log.info(f"🎯 Agree: '{agree_target['text']}' dis={agree_target['disabled']}")

        if agree_target['disabled']:
            for _ in range(5):
                await page.wait_for_timeout(1500)
                try:
                    agree_target = await page.evaluate("""
                        () => {
                            const kws = ['agree and continue', 'i agree', 'accept', 'agree'];
                            for (const el of document.querySelectorAll('button, [role="button"]')) {
                                if (el.offsetParent === null) continue;
                                const t = (el.innerText || '').trim().toLowerCase();
                                for (const kw of kws) {
                                    if (t === kw || t.includes(kw)) {
                                        const rect = el.getBoundingClientRect();
                                        const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                                        return {
                                            x: Math.round(rect.x + rect.width / 2),
                                            y: Math.round(rect.y + rect.height / 2),
                                            disabled: disabled,
                                        };
                                    }
                                }
                            }
                            return null;
                        }
                    """)
                except Exception:
                    break
                if agree_target and not agree_target.get('disabled'):
                    break

        try:
            await page.evaluate(f"""
                () => {{
                    const el = document.elementFromPoint({agree_target['x']}, {agree_target['y']});
                    if (el) el.scrollIntoView({{block: 'center', behavior: 'instant'}});
                }}
            """)
            await page.wait_for_timeout(1000)

            target2 = await page.evaluate("""
                () => {
                    const kws = ['agree and continue', 'i agree', 'accept'];
                    for (const el of document.querySelectorAll('button, [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        for (const kw of kws) {
                            if (t === kw || t.includes(kw)) {
                                const rect = el.getBoundingClientRect();
                                return {
                                    x: Math.round(rect.x + rect.width / 2),
                                    y: Math.round(rect.y + rect.height / 2),
                                };
                            }
                        }
                    }
                    return null;
                }
            """)
            if target2:
                agree_target['x'] = target2['x']
                agree_target['y'] = target2['y']

            await page.mouse.move(agree_target['x'] - 100, agree_target['y'] - 50, steps=10)
            await page.wait_for_timeout(300)
            await page.mouse.move(agree_target['x'], agree_target['y'], steps=8)
            await page.wait_for_timeout(400)
            await page.mouse.down()
            await page.wait_for_timeout(120)
            await page.mouse.up()
            log.info("✅ Agree mouse")
        except Exception as e:
            log.warning(f"❌ Agree mouse: {e}")
            for sel in [
                'button:has-text("Agree and continue")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.click(force=True, timeout=5000)
                        break
                except Exception:
                    continue

        for i in range(15):
            await page.wait_for_timeout(2000)
            try:
                gone = await page.evaluate("""
                    () => {
                        for (const el of document.querySelectorAll('[role="dialog"], [role="alertdialog"], .modal')) {
                            if (el.offsetParent === null) continue;
                            const t = (el.innerText || '').toLowerCase();
                            if (t.includes('terms of service') && t.includes('agree')) return false;
                        }
                        return true;
                    }
                """)
                if gone:
                    log.info(f"✅ Dialog اختفت ~{(i+1)*2}s")
                    break
            except Exception:
                log.info(f"⏳ {i+1}")
        log.info("✅ step2 انتهى")

    # ==================== STEP 3: Enable API ====================

    async def step3_enable_api(self, project_id: str, authuser: str):
        page = self.page
        api_url = f"https://console.cloud.google.com/apis/library/run.googleapis.com?project={project_id}&authuser={authuser}"
        log.info(f"🌐 Enable API...")
        await page.goto(api_url, wait_until="domcontentloaded")

        enable_btn = page.get_by_role("button", name="Enable")
        manage_btn = page.get_by_role("button", name="Manage")
        disable_btn = page.get_by_text("Disable API")

        try:
            await expect(enable_btn.or_(manage_btn)).to_be_visible(timeout=15000)
            if await enable_btn.is_visible():
                await enable_btn.click()
                await expect(manage_btn.or_(disable_btn)).to_be_visible(timeout=60000)
                log.info("✅ API مفعّل")
            elif await manage_btn.is_visible():
                log.info("ℹ️ API مفعّل مسبقا")
        except Exception as e:
            raise RuntimeError(f"فشل تفعيل API: {str(e)}")

    # ==================== STEP 4: Create Cloud Run ====================

    async def step4_create_cloud_run(self, project_id: str, authuser: str):
        page = self.page
        run_url = f"https://console.cloud.google.com/run/create?project={project_id}&authuser={authuser}"
        log.info(f"🌐 Create Cloud Run...")
        await page.goto(run_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        try:
            label = page.get_by_text("Container Image URL").first
            await label.click()
            await page.wait_for_timeout(500)
            await page.keyboard.type("docker.io/ajndjd2/ahmed-vip1", delay=50)
            log.info("✅ رابط الحاوية")
        except Exception as e:
            raise RuntimeError(f"فشل كتابة الرابط: {str(e)}")

        await page.wait_for_timeout(3000)

        try:
            await page.get_by_role("radio", name="Allow public access").click()
            await page.get_by_role("radio", name="Instance-based").click()
            try:
                await page.get_by_role("button", name="Hide").click(timeout=2000)
            except Exception:
                pass
            await page.keyboard.press("End")
            await page.wait_for_timeout(1000)

            create_btn = page.get_by_role("button", name="Create")
            await create_btn.click(force=True)
            log.info("✅ Create")
        except Exception as e:
            raise RuntimeError(f"فشل الإعدادات: {str(e)}")

    # ==================== STEP 5: Get URL ====================

    async def step5_get_deployed_url(self):
        page = self.page
        link_locator = page.locator('a[href*="run.app"]')
        await link_locator.wait_for(state="visible", timeout=120000)
        final_url = await link_locator.get_attribute("href")
        log.info(f"✅ URL: {final_url}")
        return final_url
