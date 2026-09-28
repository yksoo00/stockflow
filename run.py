"""
StockFlow 진입점.

- 기본: waitress(프로덕션 WSGI 서버)로 기동한다.
- FLASK_DEBUG=1 이면 Flask 개발 서버(자동 리로드, 디버거)로 기동한다. 로컬 개발 전용.

환경변수:
    HOST          바인드 주소 (기본 0.0.0.0)
    PORT          포트 (기본 51000)
    WAITRESS_THREADS  waitress 워커 스레드 수 (기본 8)
"""

import os

from app import create_app

app = create_app()


def main():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "51000"))

    if os.getenv("FLASK_DEBUG", "").strip() in {"1", "true", "True"}:
        app.run(host=host, port=port, debug=True)
        return

    from waitress import serve

    serve(
        app,
        host=host,
        port=port,
        threads=int(os.getenv("WAITRESS_THREADS", "8")),
        # 엑셀 업로드(최대 UPLOAD_MAX_MB)를 감안해 여유 있게 잡는다.
        max_request_body_size=app.config["MAX_CONTENT_LENGTH"] + 1024 * 1024,
        ident="StockFlow",
    )


if __name__ == "__main__":
    main()
