# SPDX-License-Identifier: MIT
"""啟動：python3 -m mod_ask_server [--config config.json] [--host H] [--port P]"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import signal
import sys
import threading

from . import __version__
from .app import create_server
from .config import load_config
from .errors import ConfigError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mod_ask_server",
        description="MOD-ASK 最小參考伺服器（預設只綁 127.0.0.1:8787、使用假引擎）")
    ap.add_argument("--config", help="設定檔（JSON）；不給就全用預設值")
    ap.add_argument("--host", help="覆寫 server.host")
    ap.add_argument("--port", type=int, help="覆寫 server.port")
    ap.add_argument("--version", action="version", version="mod-ask-server " + __version__)
    ap.add_argument("-v", "--verbose", action="store_true", help="顯示除錯訊息")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("mod_ask")

    try:
        cfg = load_config(args.config)
        overrides = {}
        if args.host:
            overrides["host"] = args.host
        if args.port is not None:
            overrides["port"] = args.port
        if overrides:
            cfg = dataclasses.replace(cfg, server=dataclasses.replace(cfg.server, **overrides))
        server = create_server(cfg)
    except ConfigError as e:
        print("設定錯誤：%s" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("無法啟動（埠被占用或沒有權限？）：%s" % e.strerror, file=sys.stderr)
        return 2

    log.info("mod-ask-server %s listening on %s:%d  (stt=%s llm=%s tts=%s, auth=%s, qa_log=%s, "
             "display=%s)", __version__, cfg.server.host, server.port, cfg.stt.kind,
             cfg.llm.kind, cfg.tts.kind, "on" if server.auth.enabled else "off",
             "on" if cfg.qa_log.enabled else "off",
             "on" if server.service.display else "off")

    def _terminate(signum, frame):  # noqa: ANN001
        # shutdown() 不能在跑 serve_forever 的執行緒裡呼叫，所以另開一條
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
