"""
Одноразовый скрипт для обмена авторизационного кода amoCRM на токены.
Запускается один раз, выводит полученные токены в консоль.

Использование:
  1. В amoCRM: Настройки → Интеграции → Ваша интеграция → Получить код
  2. Установите переменные окружения (или отредактируйте ниже):
     - AMOCRM_SUBDOMAIN
     - AMOCRM_CLIENT_ID
     - AMOCRM_CLIENT_SECRET
     - AMOCRM_AUTH_CODE (полученный код)
  3. Запустите: python exchange_token.py
  4. Скопируйте полученные access_token и refresh_token в Amvera

На Amvera можно запустить через веб-терминал (консоль) проекта.
"""

import os
import json
import ssl
import urllib.request
import urllib.error

# =============================================================================
# Настройки — можно задать через переменные окружения или вписать прямо сюда
# =============================================================================
AMOCRM_SUBDOMAIN = os.getenv("AMOCRM_SUBDOMAIN", "")        # например: infobeachvolleyclubru
AMOCRM_CLIENT_ID = os.getenv("AMOCRM_CLIENT_ID", "")        # ID интеграции
AMOCRM_CLIENT_SECRET = os.getenv("AMOCRM_CLIENT_SECRET", "") # Секретный ключ
AMOCRM_AUTH_CODE = os.getenv("AMOCRM_AUTH_CODE", "")         # Авторизационный код
REDIRECT_URI = "https://welcomebvcbot-annagriaznova.amvera.io"

# Если переменные не заданы — можно вписать их прямо здесь:
# AMOCRM_SUBDOMAIN = "infobeachvolleyclubru"
# AMOCRM_CLIENT_ID = "ваш-client-id"
# AMOCRM_CLIENT_SECRET = "ваш-client-secret"
# AMOCRM_AUTH_CODE = "полученный-код"

ssl_ctx = ssl.create_default_context()


def exchange_auth_code():
    """Обмен авторизационного кода на access_token и refresh_token."""

    if not AMOCRM_SUBDOMAIN:
        print("ОШИБКА: AMOCRM_SUBDOMAIN не задан!")
        print("Установите переменную окружения или впишите значение в скрипт.")
        return

    if not AMOCRM_CLIENT_ID:
        print("ОШИБКА: AMOCRM_CLIENT_ID не задан!")
        return

    if not AMOCRM_CLIENT_SECRET:
        print("ОШИБКА: AMOCRM_CLIENT_SECRET не задан!")
        return

    if not AMOCRM_AUTH_CODE:
        print("ОШИБКА: AMOCRM_AUTH_CODE не задан!")
        print("Получите код в amoCRM: Настройки → Интеграции → Ваша интеграция → Получить код")
        return

    url = f"https://{AMOCRM_SUBDOMAIN}.amocrm.ru/oauth2/access_token"

    payload = {
        "client_id": AMOCRM_CLIENT_ID,
        "client_secret": AMOCRM_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": AMOCRM_AUTH_CODE,
        "redirect_uri": REDIRECT_URI,
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"Запрос к: {url}")
    print(f"client_id: {AMOCRM_CLIENT_ID[:8]}...")
    print(f"redirect_uri: {REDIRECT_URI}")
    print(f"code: {AMOCRM_AUTH_CODE[:8]}...")
    print()
    print("Обмениваю авторизационный код на токены...")
    print()

    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))

            access_token = result.get("access_token", "")
            refresh_token = result.get("refresh_token", "")
            expires_in = result.get("expires_in", 0)
            token_type = result.get("token_type", "")

            if access_token:
                print("=" * 60)
                print("УСПЕХ! Токены получены:")
                print("=" * 60)
                print()
                print(f"access_token:")
                print(f"  {access_token}")
                print()
                print(f"refresh_token:")
                print(f"  {refresh_token}")
                print()
                print(f"token_type: {token_type}")
                print(f"expires_in: {expires_in} секунд (~{expires_in // 3600} часов)")
                print()
                print("=" * 60)
                print("СКОПИРУЙТЕ ЭТИ ЗНАЧЕНИЯ В ПЕРЕМЕННЫЕ AMVERA:")
                print("=" * 60)
                print()
                print(f"AMOCRM_ACCESS_TOKEN = {access_token}")
                print(f"AMOCRM_REFRESH_TOKEN = {refresh_token}")
                print()
                print("ВНИМАНИЕ: Авторизационный код одноразовый!")
                print("После обмена его нельзя использовать повторно.")
                print("Для обновления токенов бот будет использовать refresh_token.")
            else:
                print("ОШИБКА: В ответе нет access_token!")
                print(f"Ответ: {json.dumps(result, indent=2, ensure_ascii=False)}")

    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        print(f"ОШИБКА HTTP {e.code} {e.reason}")
        print(f"Ответ: {error_body}")

        if e.code == 400:
            print()
            print("Возможные причины:")
            print("  - Код уже был использован (коды одноразовые)")
            print("  - Код истёк (действителен 20 минут)")
            print("  - Неверный redirect_uri")
            print()
            print("Получите новый код в amoCRM и повторите.")

    except Exception as e:
        print(f"Ошибка: {e}")


if __name__ == "__main__":
    exchange_auth_code()
