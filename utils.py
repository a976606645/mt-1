import json


def parse_json(text):
    start = text.find("{")
    end = text.find("}") + 1
    return json.loads(text[start:end])
