import asyncio
from utils.logger import get_logger

log = get_logger("Deployer")


class CloudRunDeployer:
    def __init__(self, project_id: str, region: str = "us-central1"):
        self.project_id = project_id
        self.region = region

    async def deploy(self, service_name: str, image: str, memory: str = "2Gi", cpu: str = "2", port: int = 8080):
        log.info(f"🚀 نشر {service_name} → {self.project_id}/{self.region}")

        cmd = [
            "gcloud", "run", "deploy", service_name,
            "--image", image,
            "--platform", "managed",
            "--region", self.region,
            "--project", self.project_id,
            "--memory", memory,
            "--cpu", cpu,
            "--port", str(port),
            "--allow-unauthenticated",
            "--quiet",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode(errors="ignore")[:500]
            raise RuntimeError(f"فشل النشر: {err}")

        # استخراج URL
        url = await self._get_service_url(service_name)
        log.info(f"✅ {url}")
        return url

    async def _get_service_url(self, service_name: str) -> str:
        cmd = [
            "gcloud", "run", "services", "describe", service_name,
            "--region", self.region,
            "--project", self.project_id,
            "--format", "value(status.url)",
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        return stdout.decode(errors="ignore").strip()
