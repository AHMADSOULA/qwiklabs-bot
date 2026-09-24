import asyncio
import aiohttp
from utils.logger import get_logger

log = get_logger("CloudRunDeployer")


class CloudRunDeployer:
    """
    ينشر صورة Docker على Google Cloud Run مباشرة عبر REST API.
    يستعمل access token من المتصفح (Playwright).
    """

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

    async def deploy(
        self,
        service_name: str,
        image: str,
        memory: str = "4Gi",
        cpu: str = "2",
        port: int = 8080,
        allow_unauthenticated: bool = True,
    ):
        """
        ينشئ أو يحدّث خدمة Cloud Run.

        Args:
            service_name: اسم الخدمة (مثل ahmed-vip1)
            image: مسار الصورة (docker.io/ajndjd2/ahmed-vip1)
            memory: RAM (4Gi)
            cpu: عدد المعالجات (2)
            port: المنفذ اللي كيسمع فيه التطبيق (افتراضي 8080)
            allow_unauthenticated: هل يكون الرابط عام بلا مصادقة
        """
        log.info(f"نشر {service_name} على Cloud Run ({self.region})...")

        payload = {
            "template": {
                "containers": [
                    {
                        "image": image,
                        "resources": {
                            "limits": {
                                "memory": memory,
                                "cpu": cpu,
                            }
                        },
                        "ports": [{"containerPort": port}],
                    }
                ],
                "timeout": "3600s",
                "serviceAccount": "default",
            },
            "ingress": "INGRESS_TRAFFIC_ALL",
        }

        # 1. نحاول نصنع الخدمة
        create_url = (
            f"{self.API_BASE}/projects/{self.project_id}"
            f"/locations/{self.region}/services?serviceId={service_name}"
        )

        async with aiohttp.ClientSession() as session:
            # أولاً: هل موجودة من قبل؟
            existing = await self._get_service(session, service_name)
            if existing:
                log.info(f"الخدمة موجودة من قبل — سنقوم بتحديثها")
                # Update existing
                async with session.patch(
                    self._service_url(service_name),
                    headers=self.headers,
                    json=payload,
                ) as resp:
                    text = await resp.text()
                    if resp.status not in (200, 201, 202):
                        log.error(f"فشل التحديث: {resp.status} — {text[:500]}")
                        raise RuntimeError(f"Cloud Run update failed: {resp.status} — {text[:300]}")
                    operation = await resp.json()
            else:
                # Create new
                async with session.post(create_url, headers=self.headers, json=payload) as resp:
                    text = await resp.text()
                    if resp.status not in (200, 201, 202):
                        log.error(f"فشل الإنشاء: {resp.status} — {text[:500]}")
                        raise RuntimeError(f"Cloud Run create failed: {resp.status} — {text[:300]}")
                    operation = await resp.json()

            # 2. انتظر انتهاء العملية
            op_name = operation.get("name")
            if op_name:
                await self._wait_for_operation(session, op_name)

            # 3. اجعل الرابط عاماً
            if allow_unauthenticated:
                await self._set_public(session, service_name)

            # 4. اجيب الرابط النهائي
            url = await self._get_service_url(session, service_name)

        log.info(f"تم النشر بنجاح: {url}")
        return url

    async def _get_service(self, session, service_name: str):
        async with session.get(self._service_url(service_name), headers=self.headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

    async def _get_service_url(self, session, service_name: str):
        data = await self._get_service(session, service_name)
        if data:
            return data.get("uri") or data.get("status", {}).get("url")
        return None

    async def _wait_for_operation(self, session, op_name: str, max_wait: int = 300):
        url = f"https://run.googleapis.com/v2/{op_name}"
        waited = 0
        while waited < max_wait:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if data.get("done"):
                    if "error" in data:
                        raise RuntimeError(f"Cloud Run operation failed: {data['error']}")
                    return data
            await asyncio.sleep(5)
            waited += 5
        return None

    async def _set_public(self, session, service_name: str):
        """يعطي صلاحية allUsers على الخدمة (يجعل الرابط عام)."""
        # نجيب الـ IAM policy الحالية
        policy_url = f"{self._service_url(service_name)}:getIamPolicy"
        async with session.get(policy_url, headers=self.headers) as resp:
            if resp.status != 200:
                log.warning(f"تعذر جلب IAM policy: {resp.status}")
                return
            policy = await resp.json()

        # نضيف allUsers
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
                if resp.status != 200:
                    text = await resp.text()
                    log.warning(f"تعذر ضبط IAM public: {resp.status} — {text[:200]}")
                else:
                    log.info("✅ تم جعل الخدمة عامة (allUsers)")


async def extract_access_token(page) -> str:
    """
    يستخرج access token من المتصفح.
    يستعمل نفس الجلسة المسجل بها دخول في Cloud Console.
    """
    log.info("استخراج access token من المتصفح...")

    # نستعمل fetch من داخل الصفحة باش نستغلو cookies الحالية
    token = await page.evaluate("""
        async () => {
            try {
                const res = await fetch(
                    'https://run.googleapis.com/v2/projects?pageSize=1',
                    { method: 'GET' }
                );
                // هاد الطلب ما كيرجعش token مباشرة
                // لكن إذا نجح، معنى الجلسة صالحة
                return null;
            } catch(e) {
                return null;
            }
        }
    """)

    # البديل: نستخرج access token من Google Cloud Console
    # كاين طريقة: نفتح صفحة معينة و نستخرج التوكن من الـ devtools protocol
    # هادي طريقة أسهل: نستعمل Google OAuth Playground
    # ولكن هنا غادي نستعمل طريقة أخرى: نقرا التوكن من الـ localStorage ولا من cookies

    # نفتح صفحة Cloud Run Console
    await page.goto("https://console.cloud.google.com/run", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    # نحاول نستخرج من JS
    token = await page.evaluate("""
        () => {
            // Google Cloud Console كيخزن access token فـ window
            if (window.gapi && window.gapi.auth) {
                try {
                    const auth = window.gapi.auth.getToken();
                    return auth ? auth.access_token : null;
                } catch(e) {}
            }
            // طريقة أخرى: من localStorage
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                if (k && k.includes('token')) {
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
        log.warning("تعذر استخراج access token تلقائياً")
        raise RuntimeError(
            "فشل استخراج access token من المتصفح. "
            "تحقق من تسجيل الدخول لـ Cloud Console."
        )

    log.info("✅ تم استخراج access token")
    return token
