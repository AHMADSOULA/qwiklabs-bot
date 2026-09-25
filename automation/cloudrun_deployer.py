import asyncio
import aiohttp
from utils.logger import get_logger

log = get_logger("CloudRun")


class CloudRunDeployer:
    API = "https://run.googleapis.com/v2"

    def __init__(self, access_token: str, project_id: str, region: str):
        self.token = access_token
        self.project_id = project_id
        self.region = region
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": project_id,
        }

    def _url(self, service: str) -> str:
        return f"{self.API}/projects/{self.project_id}/locations/{self.region}/services/{service}"

    async def deploy(self, service_name, image, memory="2Gi", cpu="2", port=8080):
        log.info(f"🚀 نشر {service_name} على {self.region}")

        payload = {
            "template": {
                "containers": [{
                    "image": image,
                    "resources": {"limits": {"memory": memory, "cpu": cpu}},
                    "ports": [{"containerPort": port}],
                }],
                "timeout": "3600s",
            },
            "ingress": "INGRESS_TRAFFIC_ALL",
        }

        create_url = f"{self.API}/projects/{self.project_id}/locations/{self.region}/services?serviceId={service_name}"

        async with aiohttp.ClientSession() as s:
            existing = await self._get(s, service_name)
            if existing:
                log.info("تحديث خدمة موجودة...")
                async with s.patch(self._url(service_name), headers=self.headers, json=payload) as r:
                    if r.status not in (200, 201, 202):
                        raise RuntimeError(f"Update {r.status}: {(await r.text())[:300]}")
                    op = await r.json()
            else:
                async with s.post(create_url, headers=self.headers, json=payload) as r:
                    if r.status not in (200, 201, 202):
                        raise RuntimeError(f"Create {r.status}: {(await r.text())[:300]}")
                    op = await r.json()

            if op.get("name"):
                await self._wait(s, op["name"])

            await self._public(s, service_name)
            url = await self._get_url(s, service_name)

        log.info(f"✅ {url}")
        return url

    async def _get(self, s, service):
        async with s.get(self._url(service), headers=self.headers) as r:
            return await r.json() if r.status == 200 else None

    async def _get_url(self, s, service):
        d = await self._get(s, service)
        if d:
            return d.get("uri") or d.get("status", {}).get("url")
        return None

    async def _wait(self, s, op_name, max_wait=300):
        url = f"https://run.googleapis.com/v2/{op_name}"
        for _ in range(max_wait // 5):
            async with s.get(url, headers=self.headers) as r:
                if r.status != 200:
                    break
                d = await r.json()
                if d.get("done"):
                    if "error" in d:
                        raise RuntimeError(f"Op error: {d['error']}")
                    return
            await asyncio.sleep(5)

    async def _public(self, s, service):
        try:
            async with s.get(f"{self._url(service)}:getIamPolicy", headers=self.headers) as r:
                if r.status != 200:
                    return
                p = await r.json()
            b = p.get("bindings", [])
            has = any("allUsers" in x.get("members", []) for x in b if x.get("role") == "roles/run.invoker")
            if not has:
                b.append({"role": "roles/run.invoker", "members": ["allUsers"]})
                p["bindings"] = b
                await s.post(f"{self._url(service)}:setIamPolicy", headers=self.headers, json={"policy": p})
        except Exception as e:
            log.warning(f"public: {e}")


async def extract_access_token(page) -> str:
    log.info("استخراج access token...")
    await page.goto("https://console.cloud.google.com/run", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    token = await page.evaluate("""
        () => {
            if (window.gapi && window.gapi.auth) {
                try { const a = window.gapi.auth.getToken(); if (a && a.access_token) return a.access_token; } catch(e){}
            }
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                if (k && k.toLowerCase().includes('token')) {
                    try { const v = JSON.parse(localStorage.getItem(k)); if (v && v.access_token) return v.access_token; } catch(e){}
                }
            }
            return null;
        }
    """)
    if not token:
        raise RuntimeError("فشل access token")
    return token
