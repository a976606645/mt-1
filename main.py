import time
from datetime import datetime
from logger import logger
from spider import Econnoisseur

e = Econnoisseur()
e.reserve()

now = datetime.now()
day = now.day + 1 if now.hour >= 10 else now.day
seckill_time = now.replace(
    day=day,
    hour=9,
    minute=59,
    second=59,
)

logger.info("脚本将于 %s 开始抢购" % seckill_time)
while True:
    if datetime.now() > seckill_time:
        logger.info("时间到，开始抢购")
        e.seckill_by_pool()
    time.sleep(0.1)
