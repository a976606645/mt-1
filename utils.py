import json
from logger import logger


def parse_json(text):
    start = text.find("{")
    end = text.find("}") + 1
    try:
        data = json.loads(text[start:end])
        return data
    except Exception:
        logger.error("json解析失败：%s" % text)
