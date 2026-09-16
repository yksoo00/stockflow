"""
eBay App ID / Cert ID가 .env에 정상적으로 들어있는지 형식만 점검하는 스크립트.
실제 값은 절대 출력하지 않고, 길이/패턴만 확인한다.

사용법 (프로젝트 루트에서, venv 활성화 후):
    python check_ebay_creds.py
"""

import os
import re

from dotenv import load_dotenv

load_dotenv()


def mask(value):
    if not value:
        return "(비어있음)"
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def check_app_id(app_id):
    print(f"EBAY_APP_ID   길이={len(app_id)}  마스킹={mask(app_id)}")

    if not app_id:
        print("  -> 비어있습니다. .env에 값을 넣어주세요.")
        return

    # 정상 패턴 예시: yourname-appname-PRD-xxxxxxxxx-xxxxxxxx (총 40자 안팎)
    if not re.search(r"-(PRD|SBX)-", app_id):
        print("  -> 경고: '-PRD-' 또는 '-SBX-' 구간이 안 보입니다. 값이 잘렸을 수 있습니다.")
    elif len(app_id) < 30:
        print("  -> 경고: 일반적인 App ID보다 짧습니다(보통 35~45자). 앞부분(계정명-앱이름)이 잘렸을 가능성이 있습니다.")
    else:
        print("  -> 형식상으로는 큰 문제 없어 보입니다.")


def check_cert_id(cert_id):
    print(f"EBAY_CERT_ID  길이={len(cert_id)}  마스킹={mask(cert_id)}")

    if not cert_id:
        print("  -> 비어있습니다. .env에 값을 넣어주세요.")
        return

    # 정상 패턴: PRD-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (총 40자, 마지막 구간 12자리)
    match = re.match(r"^(PRD|SBX)-([0-9a-fA-F-]+)$", cert_id)

    if not match:
        print("  -> 경고: 'PRD-' 또는 'SBX-'로 시작하는 UUID 형식이 아닙니다.")
        return

    hex_part = match.group(2)
    segments = hex_part.split("-")

    print(f"  -> UUID 구간 길이: {'-'.join(str(len(s)) for s in segments)} (정상은 8-4-4-4-12)")

    if segments and len(segments[-1]) != 12:
        print("  -> 경고: 마지막 구간이 12자리가 아닙니다. 값이 중간에 잘렸을 가능성이 매우 높습니다.")
        print("     -> developer.ebay.com/my/keys 에서 Cert ID를 다시 복사(복사 아이콘 사용)해주세요.")
    else:
        print("  -> 형식상으로는 큰 문제 없어 보입니다.")


def main():
    app_id = os.getenv("EBAY_APP_ID", "").strip()
    cert_id = os.getenv("EBAY_CERT_ID", "").strip()
    env = os.getenv("EBAY_ENV", "").strip()

    print(f"EBAY_ENV = {env!r}")
    print()
    check_app_id(app_id)
    print()
    check_cert_id(cert_id)


if __name__ == "__main__":
    main()
