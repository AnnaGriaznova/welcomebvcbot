"""
amoCRM integration module for BVC Bot — БЕЗ внешних зависимостей.
Pure Python stdlib (urllib, json).

Создаёт сделку в стадии «Неразобранное» + контакт с кастомными полями.

Переменные окружения:
  AMOCRM_SUBDOMAIN      — поддомен amoCRM (из xxx.amocrm.ru)
  AMOCRM_ACCESS_TOKEN   — долгосрочный токен (access_token)
  AMOCRM_CLIENT_ID      — ID интеграции (для обновления токена)
  AMOCRM_CLIENT_SECRET  — секретный ключ (для обновления токена)
  AMOCRM_REFRESH_TOKEN  — refresh-токен (для обновления access_token)
"""

import os
import json
import ssl
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime

logger = logging.getLogger("welcomebvcbot.amocrm")

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
AMOCRM_SUBDOMAIN = os.getenv("AMOCRM_SUBDOMAIN", "")
AMOCRM_ACCESS_TOKEN = os.getenv("AMOCRM_ACCESS_TOKEN", "")
AMOCRM_CLIENT_ID = os.getenv("AMOCRM_CLIENT_ID", "")
AMOCRM_CLIENT_SECRET = os.getenv("AMOCRM_CLIENT_SECRET", "")
AMOCRM_REFRESH_TOKEN = os.getenv("AMOCRM_REFRESH_TOKEN", "")
AMOCRM_AUTH_CODE = os.getenv("AMOCRM_AUTH_CODE", "")

AMOCRM_BASE_URL = f"https://{AMOCRM_SUBDOMAIN}.amocrm.ru" if AMOCRM_SUBDOMAIN else ""

ssl_ctx = ssl.create_default_context()

# Текущий access_token (может обновляться через refresh)
_current_access_token = AMOCRM_ACCESS_TOKEN

# Кэш ID кастомных полей
_lead_fields_cache = None
_contact_fields_cache = None
_pipeline_id_cache = None

# Lock для потокобезопасного обновления токена
_token_lock = threading.Lock()


# -----------------------------------------------------------------------------
# amoCRM API helper
# -----------------------------------------------------------------------------
def _amocrm_request(method, endpoint, data=None, retry_on_401=True):
    """Вызов amoCRM API через urllib."""
    if not AMOCRM_BASE_URL:
        logger.warning("AMOCRM_SUBDOMAIN not set, skipping amoCRM request")
        return None

    url = f"{AMOCRM_BASE_URL}{endpoint}"
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_current_access_token}",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass

        if e.code == 401 and retry_on_401 and AMOCRM_REFRESH_TOKEN:
            logger.info("Got 401, trying to refresh token...")
            if _refresh_access_token():
                return _amocrm_request(method, endpoint, data, retry_on_401=False)
            else:
                logger.error("Token refresh failed, amoCRM request aborted")
                return None

        logger.error(f"amoCRM API error ({method} {endpoint}): HTTP {e.code} - {error_body}")
        return None
    except Exception as e:
        logger.error(f"amoCRM API request failed ({method} {endpoint}): {e}")
        return None


def _refresh_access_token():
    """Обновление access_token через refresh_token."""
    global _current_access_token, AMOCRM_REFRESH_TOKEN

    with _token_lock:
        url = f"{AMOCRM_BASE_URL}/oauth2/access_token"
        payload = {
            "client_id": AMOCRM_CLIENT_ID,
            "client_secret": AMOCRM_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": AMOCRM_REFRESH_TOKEN,
            "redirect_uri": "https://welcomebvcbot-annagriaznova.amvera.io",
        }
        logger.info(f"Attempting token refresh to {url}")
        logger.info(f"client_id={AMOCRM_CLIENT_ID[:8]}... "
                   f"client_secret={AMOCRM_CLIENT_SECRET[:4]}... "
                   f"refresh_token={AMOCRM_REFRESH_TOKEN[:8]}...")

        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("access_token"):
                    _current_access_token = result["access_token"]
                    AMOCRM_REFRESH_TOKEN = result.get("refresh_token", AMOCRM_REFRESH_TOKEN)
                    logger.info("SUCCESS: amoCRM access token refreshed")
                    return True
                else:
                    logger.error(f"Token refresh response missing access_token: {result}")
                    return False
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            logger.error(f"Token refresh HTTP error: {e.code} {e.reason} - Body: {error_body}")
            return False
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False


# -----------------------------------------------------------------------------
# Custom fields discovery
# -----------------------------------------------------------------------------
def _get_lead_custom_fields():
    """Получить список кастомных полей сделок."""
    global _lead_fields_cache
    if _lead_fields_cache is not None:
        return _lead_fields_cache

    result = _amocrm_request("GET", "/api/v4/leads/custom_fields")
    if result and "_embedded" in result:
        fields = result["_embedded"].get("custom_fields", [])
        _lead_fields_cache = {f["name"]: f["id"] for f in fields}
        logger.info(f"Discovered lead custom fields: {list(_lead_fields_cache.keys())}")
    else:
        _lead_fields_cache = {}
        logger.warning("No lead custom fields discovered")

    return _lead_fields_cache


def _get_contact_custom_fields():
    """Получить список кастомных полей контактов."""
    global _contact_fields_cache
    if _contact_fields_cache is not None:
        return _contact_fields_cache

    result = _amocrm_request("GET", "/api/v4/contacts/custom_fields")
    if result and "_embedded" in result:
        fields = result["_embedded"].get("custom_fields", [])
        _contact_fields_cache = {}
        for f in fields:
            _contact_fields_cache[f["name"]] = {
                "id": f["id"],
                "code": f.get("code", ""),
                "field_type": f.get("type", ""),
            }
        logger.info(f"Discovered contact custom fields: {list(_contact_fields_cache.keys())}")
    else:
        _contact_fields_cache = {}
        logger.warning("No contact custom fields discovered")

    return _contact_fields_cache


def _get_default_pipeline_id():
    """Получить ID воронки по умолчанию."""
    global _pipeline_id_cache
    if _pipeline_id_cache is not None:
        return _pipeline_id_cache

    result = _amocrm_request("GET", "/api/v4/leads/pipelines")
    if result and "_embedded" in result:
        pipelines = result["_embedded"].get("pipelines", [])
        if pipelines:
            # Берём первую (основную) воронку
            _pipeline_id_cache = pipelines[0]["id"]
            logger.info(f"Default pipeline ID: {_pipeline_id_cache}")
        else:
            _pipeline_id_cache = None
            logger.warning("No pipelines found")
    else:
        _pipeline_id_cache = None

    return _pipeline_id_cache


def _exchange_auth_code():
    """Одноразовый обмен авторизационного кода на токены."""
    global _current_access_token, AMOCRM_REFRESH_TOKEN

    if not AMOCRM_AUTH_CODE:
        return False

    logger.info("AMOCRM_AUTH_CODE detected, exchanging for tokens...")

    url = f"{AMOCRM_BASE_URL}/oauth2/access_token"
    payload = {
        "client_id": AMOCRM_CLIENT_ID,
        "client_secret": AMOCRM_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": AMOCRM_AUTH_CODE,
        "redirect_uri": "https://welcomebvcbot-annagriaznova.amvera.io",
    }
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("access_token"):
                _current_access_token = result["access_token"]
                AMOCRM_REFRESH_TOKEN = result.get("refresh_token", AMOCRM_REFRESH_TOKEN)
                logger.info("SUCCESS: Auth code exchanged! Got new access_token and refresh_token")
                # Выводим ПОЛНЫЕ токены — это одноразовая операция,
                # без полных значений нельзя обновить переменные в Amvera
                logger.info(f"=== COPY THESE VALUES TO AMVERA ENV VARS ===")
                logger.info(f"AMOCRM_ACCESS_TOKEN={_current_access_token}")
                logger.info(f"AMOCRM_REFRESH_TOKEN={AMOCRM_REFRESH_TOKEN}")
                logger.info(f"=== THEN DELETE AMOCRM_AUTH_CODE FROM AMVERA ===")
                return True
            else:
                logger.error(f"Auth code exchange response missing access_token: {result}")
                return False
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        logger.error(f"Auth code exchange failed: HTTP {e.code} {e.reason} - {error_body}")
        return False
    except Exception as e:
        logger.error(f"Auth code exchange failed: {e}")
        return False


def init_amocrm():
    """Инициализация: получить кастомные поля и pipeline при старте."""
    if not AMOCRM_SUBDOMAIN:
        logger.warning("AMOCRM_SUBDOMAIN not set, amoCRM integration disabled")
        return

    # Если задан авторизационный код — сначала обменяем его на токены
    if AMOCRM_AUTH_CODE:
        _exchange_auth_code()
    elif not AMOCRM_ACCESS_TOKEN and not AMOCRM_REFRESH_TOKEN:
        logger.warning("No amoCRM tokens set, amoCRM integration disabled")
        return

    logger.info(f"Initializing amoCRM integration (subdomain: {AMOCRM_SUBDOMAIN})...")

    _get_lead_custom_fields()
    _get_contact_custom_fields()
    _get_default_pipeline_id()

    logger.info("amoCRM integration initialized")


# -----------------------------------------------------------------------------
# Create lead + contact in amoCRM
# -----------------------------------------------------------------------------
def create_lead(name, phone, training_type, experience, location, tg_username):
    """
    Создаёт сделку в «Неразобранное» + контакт с кастомными полями.

    Поля сделки:
      - КАКОЙ_ОПЫТ_В_ВОЛЕЙБОЛЕ = experience
      - КАКОЙ_ИЗ_НАШИХ_ЦЕНТРОВ_БЫЛ_БЫ_НАИБОЛЕЕ_УДОБЕН = location

    Поля контакта:
      - Мобильный = phone
      - Взрослый/ребенок = Взрослые/Ребенок
      - Telegram (ник) = tg_username
    """
    if not AMOCRM_SUBDOMAIN:
        logger.warning("amoCRM not configured, skipping lead creation")
        return False

    lead_fields = _get_lead_custom_fields()
    contact_fields = _get_contact_custom_fields()

    # --- Собираем custom_fields_values для сделки ---
    lead_cf = []

    # Опыт
    for field_name in ["КАКОЙ ОПЫТ В ВОЛЕЙБОЛЕ", "КАКОЙ_ОПЫТ_В_ВОЛЕЙБОЛЕ",
                        "Какой опыт в волейболе"]:
        if field_name in lead_fields:
            lead_cf.append({
                "field_id": lead_fields[field_name],
                "values": [{"value": experience}],
            })
            break

    # Локация
    for field_name in ["КАКОЙ ИЗ НАШИХ ЦЕНТРОВ БЫЛ БЫ НАИБОЛЕЕ УДОБЕН",
                        "КАКОЙ_ИЗ_НАШИХ_ЦЕНТРОВ_БЫЛ_БЫ_НАИБОЛЕЕ_УДОБЕН",
                        "Какой из наших центров был бы наиболее удобен"]:
        if field_name in lead_fields:
            lead_cf.append({
                "field_id": lead_fields[field_name],
                "values": [{"value": location}],
            })
            break

    # --- Собираем custom_fields_values для контакта ---
    contact_cf = []

    # Телефон (Мобильный)
    phone_added = False
    for field_name in ["Мобильный", "Телефон", "Mobile", "Phone"]:
        if field_name in contact_fields:
            f_info = contact_fields[field_name]
            # Для встроенного поля телефона нужен enum_code
            enum_code = "MOB"
            # Проверяем есть ли перечисления у поля
            contact_cf.append({
                "field_id": f_info["id"],
                "values": [{"value": phone, "enum_code": enum_code}],
            })
            phone_added = True
            break

    if not phone_added:
        logger.warning("Phone field 'Мобильный' not found in amoCRM contact fields")

    # Взрослый/ребенок
    adult_child_value = "Взрослые" if training_type == "Взрослые" else "Ребенок"
    for field_name in ["Взрослый/ребенок", "Взрослый / ребенок",
                        "Взрослый/ребёнок", "Взрослый / ребёнок"]:
        if field_name in contact_fields:
            f_info = contact_fields[field_name]
            contact_cf.append({
                "field_id": f_info["id"],
                "values": [{"value": adult_child_value}],
            })
            break

    # Telegram
    for field_name in ["Telegram (ник)", "Telegram", "Telegram ник"]:
        if field_name in contact_fields:
            f_info = contact_fields[field_name]
            contact_cf.append({
                "field_id": f_info["id"],
                "values": [{"value": tg_username}],
            })
            break

    # --- Формируем запрос ---
    lead_name = f"Заявка: {name}"

    payload = [
        {
            "source_name": "Telegram Bot BVC",
            "source_uid": "bvc_tg_bot",
            "created_at": int(datetime.now().timestamp()),
            "_embedded": {
                "leads": [
                    {
                        "name": lead_name,
                        "price": 0,
                        "custom_fields_values": lead_cf,
                    }
                ],
                "contacts": [
                    {
                        "name": name,
                        "custom_fields_values": contact_cf,
                    }
                ],
            },
        }
    ]

    pipeline_id = _get_default_pipeline_id()
    if pipeline_id:
        payload[0]["pipeline_id"] = pipeline_id

    logger.info(f"Creating amoCRM unsorted lead for: {name} ({phone})")

    result = _amocrm_request("POST", "/api/v4/leads/unsorted", payload)

    if result and "_embedded" in result:
        items = result["_embedded"].get("items", [])
        if items:
            lead_id = items[0].get("id", "?")
            contact_id = items[0].get("_embedded", {}).get("contacts", [{}])
            if contact_id:
                contact_id = contact_id[0].get("id", "?")
            logger.info(f"SUCCESS: amoCRM lead created (lead_id={lead_id}, contact_id={contact_id})")
            return True

    logger.error(f"ERROR: Failed to create amoCRM lead. Response: {result}")
    return False
