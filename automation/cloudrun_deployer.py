import asyncio
import aiohttp
from utils.logger import get_logger

log = get_logger("CloudRunDeployer")


class CloudRunDeployer:
    API_BASE = "https://run.googleapis.com/v2"

    def __init__(self, access_token: str, project_id: str, region: str = "us-central1"):
        self.token = access_token
        self.project_id = project_id
        self.region = region
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": project_id,
        }

    def _service_url(self, service_name: str) -> str:
        return (
            f"{self.API_BASE}/projects/{self.project_id}"
            f"/locations/{self.region}/services/{service_name}"
        )

    async def deploy(self, service_name, image, memory="2Gi", cpu="2",
                     port=8080, allow_unauthenticated=True):
        log.info(f"نشر {service_name}...")

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

        create_url = (
            f"{self.API_BASE}/projects/{self.project_id}"
            f"/locations/{self.region}/services?serviceId={service_name}"
        )

        async with aiohttp.ClientSession() as session:
            existing = await self._get_service(session, service_name)
            if existing:
                async with session.patch(
                    self._service_url(service_name),
                    headers=self.headers, json=payload,
                ) as resp:
                    text = await resp.text()
                    if resp.status not in (200, 201, 202):
                        raise RuntimeError(f"Update: {resp.status} {text[:300]}")
                    operation = await resp.json()
            else:
                async with session.post(create_url, headers=self.headers, json=payload) as resp:
                    text = await resp.text()
                    if resp.status not in (200, 201, 202):
                        raise RuntimeError(f"Create: {resp.status} {text[:300]}")
                    operation = await resp.json()

            op_name = operation.get("name")
            if op_name:
                await self._wait_for_operation(session, op_name)

            if allow_unauthenticated:
                await self._set_public(session, service_name)

            url = await self._get_service_url(session, service_name)

        log.info(f"✅ {url}")
        return url

    async def _get_service(self, session, service_name):
        async with session.get(self._service_url(service_name), headers=self.headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

    async def _get_service_url(self, session, service_name):
        data = await self._get_service(session, service_name)
        if data:
            return data.get("uri") or data.get("status", {}).get("url")
        return None

    async def _wait_for_operation(self, session, op_name, max_wait=300):
        url = f"https://run.googleapis.com/v2/{op_name}"
        waited = 0
        while waited < max_wait:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if data.get("done"):
                    if "error" in data:
                        raise RuntimeError(f"Op: {data['error']}")
                    return data
            await asyncio.sleep(5)
            waited += 5
        return None

    async def _set_public(self, session, service_name):
        policy_url = f"{self._service_url(service_name)}:getIamPolicy"
        async with session.get(policy_url, headers=self.headers) as resp:
            if resp.status != 200:
                return
            policy = await resp.json()

        bindings = policy.get("bindings", [])
        has_public = any(
            "allUsers" in b.get("members", [])
            for b in bindings
            if b.get("role") == "roles/run.invoker"
        )
        if not has_public:
            bindings.append({
                "role": "roles/run.invoker",
                "members": ["allUsers"],
            })
            policy["bindings"] = bindings
            set_url = f"{self._service_url(service_name)}:setIamPolicy"
            async with session.post(set_url, headers=self.headers, json={"policy": policy}) as resp:
                if resp.status == 200:
                    log.info("✅ public")


async def extract_access_token(page) -> str:
    log.info("استخراج access token...")
    await page.goto("https://console.cloud.google.com/run", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    token = await page.evaluate("""
        () => {
            if (window.gapi && window.gapi.auth) {
                try {
                    const auth = window.gapi.auth.getToken();
                    if (auth && auth.access_token) return auth.access_token;
                } catch(e) {}
            }
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                if (k && k.toLowerCase().includes('token')) {
                    try {
                        const v = JSON.parse(localStorage.getItem(k));
                        if (v && v.access_token) return v.access_token;
                    } catch(e) {}
                }
            }
            return null;
        }
    """)
    if not token:
        raise RuntimeError("فشل access token")
    return token
