from __future__ import annotations

import os
import sys
from typing import Any, Generator, MutableMapping, NoReturn

from sentry.services.base import Service

PYUWSGI_PROG = """\
import os
import sys

orig = sys.getdlopenflags()
sys.setdlopenflags(orig | os.RTLD_GLOBAL)
try:
    import pyuwsgi
finally:
    sys.setdlopenflags(orig)

pyuwsgi.run()
"""


def convert_options_to_env(options: dict[str, Any]) -> Generator[tuple[str, str], None, None]:
    for k, v in options.items():
        if v is None:
            continue
        key = "UWSGI_" + k.upper().replace("-", "_")
        if isinstance(v, str):
            value = v
        elif v is True:
            value = "true"
        elif v is False:
            value = "false"
        elif isinstance(v, int):
            value = str(v)
        else:
            raise TypeError(f"Unknown option type: {k!r} ({type(v)})")
        yield key, value


class SentryHTTPServer(Service):
    name = "http"

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        debug: bool = False,
        workers: int | None = None,
        validate: bool = True,
        extra_options: dict[str, Any] | None = None,
    ) -> None:
        from django.conf import settings

        from sentry import options as sentry_options
        from sentry.logging import LoggingFormat

        if validate:
            self.validate_settings()

        host = host or settings.SENTRY_WEB_HOST
        port = port or settings.SENTRY_WEB_PORT

        options = (settings.SENTRY_WEB_OPTIONS or {}).copy()
        if extra_options is not None:
            for k, v in extra_options.items():
                options[k] = v
        options.setdefault("module", "sentry.wsgi:application")
        options.setdefault("protocol", "http")
        options.setdefault("auto-procname", True)
        options.setdefault("procname-prefix-spaced", "[Sentry]")
        options.setdefault("workers", 1)
        options.setdefault("threads", 2)
        options.setdefault("http-timeout", 30)
        options.setdefault("vacuum", True)
        options.setdefault("thunder-lock", True)
        options.setdefault("log-x-forwarded-for", False)
        options.setdefault("buffer-size", 32768)
        options.setdefault("post-buffering", 65536)
        options.setdefault("limit-post", 20971520)
        options.setdefault("need-app", True)
        options.setdefault("disable-logging", False)
        options.setdefault("memory-report", True)
        options.setdefault("reload-on-rss", 600)
        options.setdefault("ignore-sigpipe", True)
        options.setdefault("ignore-write-errors", True)
        options.setdefault("disable-write-exception", True)
        options.setdefault("binary-path", sys.executable)
        options.setdefault("virtualenv", sys.prefix)
        options.setdefault("die-on-term", True)
        options.setdefault(
            "log-format",
            '%(addr) - %(user) [%(ltime)] "%(method) %(uri) %(proto)" %(status) %(size) "%(referer)" "%(uagent)"',
        )

        options.setdefault("%s-socket" % options["protocol"], f"{host}:{port}")

        # We only need to set uid/gid when stepping down from root, but if
        # we are trying to run as root, then ignore it entirely.
        uid = os.getuid()
        if uid > 0:
            options.setdefault("uid", uid)
        gid = os.getgid()
        if gid > 0:
            options.setdefault("gid", gid)

        # Required arguments that should not be overridden
        options["master"] = True
        options["enable-threads"] = True
        options["lazy-apps"] = True
        options["single-interpreter"] = True

        if workers:
            options["workers"] = workers

        # Old options from gunicorn
        if "bind" in options:
            options["%s-socket" % options["protocol"]] = options.pop("bind")
        if "accesslog" in options:
            if options["accesslog"] != "-":
                options["logto"] = options["accesslog"]
            del options["accesslog"]
        if "errorlog" in options:
            if options["errorlog"] != "-":
                options["logto2"] = options["errorlog"]
            del options["errorlog"]
        if "timeout" in options:
            options["http-timeout"] = options.pop("timeout")
        if "proc_name" in options:
            options["procname-prefix-spaced"] = options.pop("proc_name")
        if "secure_scheme_headers" in options:
            del options["secure_scheme_headers"]
        if "loglevel" in options:
            del options["loglevel"]

        # For machine logging, we are choosing to 100% disable logging
        # from uwsgi since it's currently not possible to get a nice json
        # logging out of uwsgi, so it's better to just opt out. There's
        # also an assumption that anyone operating at the scale of needing
        # machine formatted logs, they are also using nginx in front which
        # has it's own logs that can be formatted correctly.
        if sentry_options.get("system.logging-format") == LoggingFormat.MACHINE:
            options["disable-logging"] = True

        self.options = options
        self.debug = debug

    def validate_settings(self) -> None:
        from django.conf import settings as django_settings

        from sentry.utils.settings import validate_settings

        validate_settings(django_settings)

    def prepare_environment(self, env: MutableMapping[str, str] | None = None) -> None:
        from django.conf import settings

        if env is None:
            env = os.environ

        # Move all of the options into UWSGI_ env vars
        for k, v in convert_options_to_env(self.options):
            env.setdefault(k, v)

        # Signal that we're running within uwsgi
        env["SENTRY_RUNNING_UWSGI"] = "1" if settings.SENTRY_USE_UWSGI else "0"

        # This has already been validated inside __init__
        env["SENTRY_SKIP_BACKEND_VALIDATION"] = "1"

        # Look up the bin directory where `sentry` exists, which should be
        # sys.argv[0], then inject that to the front of our PATH so we can reliably
        # find the `uwsgi` that's installed when inside virtualenv.
        # This is so the virtualenv doesn't need to be sourced in, which effectively
        # does exactly this.
        virtualenv_path = os.path.dirname(os.path.abspath(sys.argv[0]))
        current_path = env.get("PATH", "")
        if virtualenv_path not in current_path:
            env["PATH"] = f"{virtualenv_path}:{current_path}"

    def run(self) -> NoReturn:
        self.prepare_environment()
        if self.debug or os.environ.get("SENTRY_RUNNING_UWSGI") == "0":
            from wsgiref.simple_server import make_server

            from sentry.wsgi import application

            assert os.environ.get("UWSGI_MODULE") == "sentry.wsgi:application"

            host, port = os.environ["UWSGI_HTTP_SOCKET"].split(":")
            httpd = make_server(host, int(port), application)  # type: ignore[arg-type]  # typeddjango/django-stubs#1053
            httpd.serve_forever()
            raise AssertionError("unreachable")
        else:
            # TODO: https://github.com/lincolnloop/pyuwsgi-wheels/pull/17
            cmd = (sys.executable, "-c", PYUWSGI_PROG)
            os.execvp(cmd[0], cmd)
