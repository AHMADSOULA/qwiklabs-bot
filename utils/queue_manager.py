"""
Queue Manager — إدارة طابور المهام
"""
import asyncio
import time
from utils.logger import get_logger

log = get_logger("Queue")


class QueueManager:
    def __init__(self):
        self.queue = []  # [{user_id, job_id, sso_url, sender, ...}]
        self.counter = 0
        self.current = None
        self.lock = asyncio.Lock()
        self.frozen_timeout = 20  # ✅ 20 ثانية

    def next_number(self) -> int:
        """يعطي رقم تسلسلي جديد"""
        self.counter += 1
        return self.counter

    async def add(self, user_id: int, job_id: int, sso_url: str,
                  sender=None, context=None) -> int:
        """يضيف مهمة للطابور"""
        async with self.lock:
            num = self.next_number()
            item = {
                "num": num,
                "user_id": user_id,
                "job_id": job_id,
                "sso_url": sso_url,
                "sender": sender,
                "context": context,
                "added_at": time.time(),
                "frozen_since": None,
                "last_update": time.time(),
            }
            self.queue.append(item)
            log.info(f"📥 #{num} أضيف — المجموع: {len(self.queue)}")
            return num

    async def get_next(self):
        """يجيب المهمة الجاية"""
        async with self.lock:
            if self.current is not None:
                return None
            if not self.queue:
                return None
            self.current = self.queue.pop(0)
            self.current["started_at"] = time.time()
            self.current["frozen_since"] = None
            return self.current

    async def finish_current(self):
        """ينهي المهمة الحالية"""
        async with self.lock:
            if self.current:
                log.info(f"✅ #{self.current['num']} انتهى")
                self.current = None

    async def mark_frozen(self):
        """يعلّم المهمة الحالية كمجودة"""
        async with self.lock:
            if self.current:
                self.current["frozen_since"] = time.time()
                log.warning(f"⚠️ #{self.current['num']} تجمد")

    async def is_frozen(self) -> bool:
        """يتحقق واش المهمة الحالية مجمدة (أكثر من 20 ثانية)"""
        if not self.current:
            return False
        frozen = self.current.get("frozen_since")
        if not frozen:
            return False
        return (time.time() - frozen) > self.frozen_timeout

    async def unfreeze(self):
        """يفك التجميد (تحديث آخر وقت)"""
        async with self.lock:
            if self.current:
                self.current["frozen_since"] = None
                self.current["last_update"] = time.time()

    def queue_size(self) -> int:
        return len(self.queue)

    def is_busy(self) -> bool:
        return self.current is not None


# ✅ Singleton
queue_manager = QueueManager()
