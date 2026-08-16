import base64
import hashlib
import json
import os
import pathlib
import re
import time
import urllib.parse
import urllib.request

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

STEP = "M93#49deLe$9B.30"
LOCAL_KEY = b"Xes50LmeNsU_4oO2"
LOCAL_IV = b"Msg4J9_38nSXD3Ld"
COMMON = {"appn": "meoof", "lang": "chinese", "ostype": "android", "tzsec": "28800"}


def _md5(value):
    return hashlib.md5(value.encode()).hexdigest()


def normalize_userid(userid):
    value = userid.replace(" ", "")
    if re.fullmatch(r"1\d{10}", value):
        return "+86-" + value
    if re.fullmatch(r"(?:\+?86)-?1\d{10}", value):
        digits = value.replace("+", "").replace("-", "")
        return "+86-" + digits[2:]
    return value


def _request(server, params):
    url = f"http://app{server}.meoof-pet.com/Meoof_Server/server.php?" + urllib.parse.urlencode(params | COMMON)
    request = urllib.request.Request(url, headers={"User-Agent": "okhttp/4.9.3", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode())
    if result.get("code") != 20000:
        raise RuntimeError(f"Meoof server returned {result.get('code')}")
    message = result.get("msg")
    if isinstance(message, str):
        try:
            return json.loads(message)
        except json.JSONDecodeError:
            return {"message": message}
    return message or {}


def request_code(userid, server=0):
    userid = normalize_userid(userid)
    platform = "phone" if userid.startswith("+") else "mail"
    return _request(server, {"cmd": "reqlogincaptcha", "userid": userid,
        "platform": platform, "sms": "ali" if platform == "phone" else ""})


def _decrypt_password(value):
    clear = AES.new(LOCAL_KEY, AES.MODE_CBC, LOCAL_IV).decrypt(base64.b64decode(value))
    return unpad(clear, 16).decode()


def login_with_code(userid, code, server=0):
    userid = normalize_userid(userid)
    platform = "phone" if userid.startswith("+") else "mail"
    challenge = _request(server, {"cmd": "random", "userid": userid,
        "platform": platform, "ask": "captchalogin"})
    random_value = challenge.get("random", challenge.get("message"))
    if not random_value:
        raise RuntimeError("Missing login challenge")
    scode = _md5(random_value + STEP)
    token = _md5("home-assistant-meoof-" + userid)
    info = _request(server, {"cmd": "captchalogin", "petlist": "userpet",
        "userid": userid, "platform": platform, "captcha": code, "scode": scode,
        "sms": "ali" if platform == "phone" else "", "token": token})
    items = list(info.get("devList") or info.get("dev") or [])
    for family in info.get("fdev") or info.get("familyDeviceList") or []:
        if isinstance(family, dict):
            items.extend(family.get("dev") or family.get("deviceList") or [family])
    devices, seen = [], set()
    for item in items:
        uid = item.get("uid") or item.get("devid")
        encrypted = item.get("pwd") or item.get("devpw")
        if not uid or not encrypted or uid in seen:
            continue
        seen.add(uid)
        devices.append({"uid": uid, "password": _decrypt_password(encrypted),
            "account": item.get("account") or item.get("devusr") or "admin",
            "name": item.get("name") or item.get("devalias") or "",
            "unit_type": item.get("unitType") or item.get("unittype") or ""})
    return {"server": server, "userid": userid, "platform": platform,
        "token": token, "scode": scode, "devices": devices}


def save_login(path, login):
    path = pathlib.Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(login, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)


def _paged_history(login, command, days, page_size):
    if not login.get("scode"):
        raise RuntimeError("cloud_reauthentication_required")
    now = int(time.time())
    records = {}
    windows = [(now - days * 86400, now)] if days <= 2 else [
        (max(now - days * 86400, end - 2 * 86400), end)
        for end in range(now, now - days * 86400, -2 * 86400)
    ]
    for start, end in windows:
        params = {"cmd": command, "petlist": "userpet", "id": 0, "order": 1,
        "pnum": page_size, "stime": start, "etime": end,
        "userid": login["userid"], "platform": login["platform"], "scode": login["scode"]}
        if login.get("devices"):
            params["devid"] = login["devices"][0]["uid"]
        result = _request(int(login.get("server", 0)), params)
        for device in result if isinstance(result, list) else []:
            if isinstance(device, dict):
                for record in device.get("flist") or []:
                    records[str(record.get("id") or (record.get("evt"), len(records)))] = record
    values = sorted(records.values(), key=lambda item: int(item.get("evt", 0) or 0), reverse=True)
    return {"ok": True, "records": values, "count": len(values)}


def feed_history(login, days=30, page_size=50):
    return _paged_history(login, "dayfeed", days, page_size)


def foraging_history(login, days=30, page_size=50):
    """Return the app's separate cat-approach/foraging event history."""
    return _paged_history(login, "dayclose", days, page_size)
