#!/usr/bin/env python3
"""Manage this checkout's loopback-only development services without Docker.

Commands: init, start, stop, status, build. No command installs software or
deletes database files. Existing non-empty databases are never re-imported.
Run this script with Python 3.9 or newer. Credentials stay in secrets.json;
database passwords are passed to child processes through their environment.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from typing import Callable, Optional
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / ".local-dev"
RUNTIME = ROOT.parent / ".local-runtime"
LOGS = DEV / "logs"
DATA = DEV / "data"
STATE = DEV / "processes.json"
SECRETS = DEV / "secrets.json"
MYSQL_DATA = DATA / "mysql"
MYSQL_SOCKET = DEV / "mysql.sock"
PROFILE = DEV / "application-navio-local.yaml"
JAR = ROOT / "yudao-server" / "target" / "yudao-server.jar"
ASSETS = DEV / "bootstrap" / "assets"
MAVEN_CACHE = DEV / "bootstrap" / "maven_cache.py"
DATABASE = "navio_mall"
APP_USER = "navio_local"
MARKER = "__navio_local_bootstrap"
PORTS = {"mysql": 13306, "redis": 16379, "assets": 48081, "backend": 48080, "maven-cache": 18082}
SQL_FILES = [
    ROOT / "sql" / "mysql" / "ruoyi-vue-pro.sql",
    ROOT / "sql" / "mysql" / "quartz.sql",
    DEV / "bootstrap" / "generated-mall-schema.sql",
    DEV / "bootstrap" / "local-demo-seed.sql",
]


class DevError(Exception):
    pass


def atomic_json(path: Path, value: dict) -> None:
    """Only replace files owned by this local manager; do not print contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def private_text(path: Path, text: str) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.chmod(path, 0o600)


def process_info(pid: int) -> Optional[dict]:
    if not isinstance(pid, int) or pid <= 1:
        return None
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "stat=", "-o", "lstart=", "-o", "command="],
            text=True, capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = result.stdout.strip()
    # Ignore zombies; a child may await reaping after a clean shutdown.
    # stat is followed by five lstart fields, then the command.
    parts = line.split(None, 6)
    if result.returncode != 0 or len(parts) != 7 or parts[0].startswith("Z"):
        return None
    return {"pid": pid, "started": " ".join(parts[1:6]), "command": parts[6]}


def owned_process(name: str, info: Optional[dict]) -> bool:
    if not info:
        return False
    command = info["command"]
    if name == "mysql":
        return "mysqld" in command and f"--datadir={MYSQL_DATA}" in command
    if name == "redis":
        # Redis rewrites its process title, so the native PID file is also
        # checked against the manager's saved start time below.
        return "redis-server" in command and (
            str(DEV / "redis.conf") in command or "127.0.0.1:16379" in command
        )
    if name == "assets":
        return "http.server" in command and str(ASSETS) in command and "48081" in command
    if name == "backend":
        return str(JAR) in command and "navio-local" in command
    if name == "maven-cache":
        return str(MAVEN_CACHE) in command
    return False


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def http_status(port: int, path: str = "/") -> dict:
    # Ignore proxy environment variables: these probes must stay on loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            result = {"reachable": True, "httpStatus": response.status}
            if path == "/actuator/health":
                try:
                    result["health"] = json.loads(response.read(65536)).get("status")
                except (ValueError, AttributeError):
                    result["health"] = None
            return result
    except urllib.error.HTTPError as error:
        return {"reachable": True, "httpStatus": error.code}
    except (OSError, urllib.error.URLError):
        return {"reachable": False}


def backend_readiness() -> dict:
    """Use the actual public template API; this build does not expose Actuator."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        "http://127.0.0.1:48080/app-api/promotion/diy-template/used",
        headers={"tenant-id": "1", "terminal": "10"},
    )
    try:
        with opener.open(request, timeout=3) as response:
            body = json.loads(response.read(262144))
            data = body.get("data") or {}
            return {"reachable": True, "httpStatus": response.status,
                    "businessCode": body.get("code"),
                    "templateReady": bool(data.get("id") and data.get("home") and data.get("user"))}
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return {"reachable": False, "templateReady": False}


class Manager:
    def __init__(self) -> None:
        self.credentials: dict = {}
        self.records = self.read_json(STATE, {})

    @staticmethod
    def read_json(path: Path, default: dict) -> dict:
        if not path.exists():
            return default
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise DevError(f"Cannot read manager-owned JSON file: {path.name}") from error
        if not isinstance(value, dict):
            raise DevError(f"Invalid manager-owned JSON file: {path.name}")
        return value

    def redact(self, text: str) -> str:
        for value in self.credentials.values():
            if isinstance(value, str) and len(value) >= 12:
                text = text.replace(value, "[redacted]")
        return text

    def directories(self) -> None:
        for directory in [DEV, LOGS, DATA, DEV / "run", DEV / "tool-home"]:
            directory.mkdir(parents=True, exist_ok=True)

    def load_credentials(self, create: bool = False) -> dict:
        if SECRETS.exists():
            self.credentials = self.read_json(SECRETS, {})
            for name in ["mysql_root_password", "mysql_app_password", "redis_password"]:
                if not re.fullmatch(r"[0-9a-f]{64}", str(self.credentials.get(name, ""))):
                    raise DevError(f"Invalid generated credential field: {name}; no data changed")
            os.chmod(SECRETS, 0o600)
        elif create:
            if MYSQL_DATA.exists() and any(MYSQL_DATA.iterdir()):
                raise DevError("MySQL data exists but secrets.json is missing; refusing to replace credentials")
            self.credentials = {
                "version": 1,
                "mysql_root_password": secrets.token_hex(32),
                "mysql_app_password": secrets.token_hex(32),
                "redis_password": secrets.token_hex(32),
            }
            atomic_json(SECRETS, self.credentials)
        else:
            raise DevError("Local credentials are missing; run init first")
        return self.credentials

    def binary(self, name: str) -> Path:
        patterns = {
            "java": ["amazon-corretto-17*.jdk/Contents/Home/bin/java"],
            "mvn": ["apache-maven-3.9.*/bin/mvn"],
            "mysqld": ["mysql-8.4*/bin/mysqld"],
            "mysql": ["mysql-8.4*/bin/mysql"],
            "mysqladmin": ["mysql-8.4*/bin/mysqladmin"],
            "redis-server": ["redis-7.4*/src/redis-server"],
            "redis-cli": ["redis-7.4*/src/redis-cli"],
        }
        matches = sorted({p.resolve() for pattern in patterns[name] for p in RUNTIME.glob(pattern) if p.is_file()})
        matches = [p for p in matches if p.is_relative_to(RUNTIME.resolve())]
        if not matches:
            raise DevError(f"Missing {name} under {RUNTIME}; install/build the requested local runtime first")
        if len(matches) > 1:
            raise DevError(f"Multiple {name} runtimes found under {RUNTIME}; keep one explicit version")
        if not os.access(matches[0], os.X_OK):
            raise DevError(f"Runtime is not executable: {matches[0]}")
        return matches[0]

    @staticmethod
    def child_environment() -> dict:
        environment = os.environ.copy()
        for key in ["MYSQL_PWD", "REDISCLI_AUTH", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"]:
            environment.pop(key, None)
        return environment

    def save_records(self) -> None:
        atomic_json(STATE, self.records)

    def existing(self, name: str, adopt: bool = True) -> Optional[dict]:
        record = self.records.get(name)
        if isinstance(record, dict):
            info = process_info(record.get("pid", 0))
            if info:
                if not owned_process(name, info) or info["started"] != record.get("started"):
                    raise DevError(f"Recorded {name} PID is no longer the same owned process; it was left untouched")
                return info
        if not adopt:
            return None
        # Recover daemon PID files created inside this checkout. Do not search
        # arbitrary processes or adopt another service merely because its port matches.
        pidfile = {"mysql": DEV / "run/mysql.pid", "redis": DEV / "run/redis.pid"}.get(name)
        if pidfile and pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
            except (OSError, ValueError):
                pid = 0
            info = process_info(pid)
            if owned_process(name, info):
                if name == "redis" and str(DEV / "redis.conf") not in info["command"]:
                    # A rewritten Redis title alone does not prove ownership
                    # without an existing start-time record.
                    return None
                self.records[name] = {"pid": pid, "started": info["started"]}
                if name == "mysql":
                    self.records[name]["bootstrap"] = "--skip-networking" in info["command"]
                self.save_records()
                return info
        return None

    def spawn(self, name: str, command: list, environment: Optional[dict] = None, **extra) -> int:
        current = self.existing(name)
        if current:
            return current["pid"]
        if port_open(PORTS[name]):
            raise DevError(f"Port {PORTS[name]} is occupied by an unmanaged process; it was left untouched")
        self.directories()
        logfile = LOGS / f"{name}.console.log"
        with logfile.open("ab", buffering=0) as output:
            process = subprocess.Popen(
                [str(part) for part in command], cwd=ROOT,
                env=environment or self.child_environment(), stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            )
        time.sleep(0.15)
        info = process_info(process.pid)
        if process.poll() is not None or not owned_process(name, info):
            raise DevError(f"{name} exited or could not be verified; see {logfile}")
        self.records[name] = {"pid": process.pid, "started": info["started"], **extra}
        self.save_records()
        return process.pid

    def wait(self, name: str, predicate: Callable[[], bool], timeout: int) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.existing(name, adopt=False):
                raise DevError(f"{name} stopped before becoming ready; see {LOGS / (name + '.console.log')}")
            if predicate():
                return
            time.sleep(0.4)
        raise DevError(f"{name} readiness timed out; process may still be running; see {LOGS}")

    def run(self, command: list, environment: Optional[dict] = None,
            input_text: Optional[str] = None, timeout: int = 30) -> str:
        try:
            result = subprocess.run(
                [str(part) for part in command], cwd=ROOT,
                env=environment or self.child_environment(), input=input_text,
                text=True, capture_output=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise DevError("Local command timed out; no data was deleted") from error
        if result.returncode != 0:
            detail = self.redact((result.stderr or "Command failed").strip())[-2500:]
            raise DevError(detail)
        return result.stdout.strip()

    def mysql(self, sql: str, password: Optional[str] = None, database: Optional[str] = None,
              tcp: bool = False, user: str = "root", timeout: int = 30) -> str:
        environment = self.child_environment()
        if password:
            environment["MYSQL_PWD"] = password
        command = [self.binary("mysql"), "--no-defaults", "--connect-timeout=3", "--batch", "--skip-column-names",
                   "--default-character-set=utf8mb4", "--binary-mode=1", f"--user={user}"]
        if tcp:
            command += ["--protocol=TCP", "--host=127.0.0.1", "--port=13306"]
        else:
            command += ["--protocol=SOCKET", f"--socket={MYSQL_SOCKET}"]
        if database:
            command += [f"--database={database}"]
        return self.run(command, environment, input_text=sql, timeout=timeout)

    def root_ready(self, allow_blank: bool = False) -> bool:
        candidates = [self.credentials["mysql_root_password"]]
        if allow_blank:
            candidates.append(None)
        for password in candidates:
            try:
                if self.mysql("SELECT 1;", password=password) == "1":
                    return True
            except DevError:
                pass
        return False

    def start_mysql(self, bootstrap: bool = False) -> None:
        mysqld = self.binary("mysqld")
        basedir = mysqld.parent.parent
        command = [mysqld, "--no-defaults", f"--basedir={basedir}", f"--datadir={MYSQL_DATA}",
                   f"--socket={MYSQL_SOCKET}", "--port=13306", "--bind-address=127.0.0.1",
                   "--mysqlx=OFF", "--skip-log-bin", "--skip-name-resolve",
                   f"--pid-file={DEV / 'run/mysql.pid'}", f"--log-error={LOGS / 'mysql.log'}"]
        if bootstrap:
            command.append("--skip-networking")
        self.spawn("mysql", command, bootstrap=bootstrap)
        self.wait("mysql", lambda: self.root_ready(allow_blank=bootstrap), 90)

    def stop_one(self, name: str, timeout: int = 35) -> None:
        info = self.existing(name, adopt=False)
        if not info:
            self.records.pop(name, None)
            self.save_records()
            return
        # Verify command and creation time once more immediately before signaling.
        latest = process_info(info["pid"])
        if not owned_process(name, latest) or latest["started"] != info["started"]:
            raise DevError(f"{name} ownership changed; no signal sent")
        os.kill(info["pid"], signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = process_info(info["pid"])
            if not current or current["started"] != info["started"]:
                self.records.pop(name, None)
                self.save_records()
                return
            time.sleep(0.3)
        raise DevError(f"{name} did not exit after SIGTERM; no forced kill was sent")

    @staticmethod
    def bootstrap_hashes() -> dict:
        hashes = {}
        for path in SQL_FILES:
            if not path.is_file():
                raise DevError(f"Missing bootstrap SQL: {path}; generate it before init")
            if re.search(r"(?im)^\s*(?:USE\s+|CREATE\s+DATABASE\b)", path.read_text()):
                raise DevError(f"Bootstrap SQL switches databases: {path.name}; refusing to import outside {DATABASE}")
            hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes

    def initialize(self) -> None:
        self.directories()
        hashes = self.bootstrap_hashes()
        self.binary("mysql")
        mysqld = self.binary("mysqld")
        self.load_credentials(create=True)
        if not (MYSQL_DATA / "mysql").is_dir():
            if MYSQL_DATA.exists() and any(MYSQL_DATA.iterdir()):
                raise DevError("MySQL data directory is non-empty but incomplete; refusing to initialize or delete it")
            MYSQL_DATA.mkdir(parents=True, exist_ok=True)
            self.run([mysqld, "--no-defaults", "--initialize-insecure", f"--basedir={mysqld.parent.parent}",
                      f"--datadir={MYSQL_DATA}", f"--log-error={LOGS / 'mysql-initialize.log'}"], timeout=180)
        current = self.existing("mysql")
        if not current:
            self.start_mysql(bootstrap=True)
        elif not self.root_ready(allow_blank=bool(self.records["mysql"].get("bootstrap"))):
            raise DevError("Managed MySQL is running but root authentication failed; no credentials changed")

        root_password = self.credentials["mysql_root_password"]
        try:
            self.mysql("SELECT 1;", password=root_password)
        except DevError:
            if not self.records["mysql"].get("bootstrap"):
                raise DevError("Root authentication failed outside socket-only bootstrap; no password reset attempted")
            # Generated credentials contain only hex digits and never come from
            # command-line/user SQL input. No password is included in argv or logs.
            self.mysql(f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_password}';", password=None)

        self.mysql(f"CREATE DATABASE IF NOT EXISTS `{DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
                   password=root_password)
        count = int(self.mysql(
            f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{DATABASE}';", password=root_password))
        marker_exists = self.mysql(
            f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{DATABASE}' AND table_name='{MARKER}';",
            password=root_password) == "1"
        imported = False
        if count == 0:
            for path in SQL_FILES:
                print(f"Importing new empty database: {path.relative_to(ROOT)}", flush=True)
                self.mysql(path.read_text(), password=root_password, database=DATABASE, timeout=600)
            self.mysql(f"CREATE TABLE `{MARKER}` (id INT PRIMARY KEY, completed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);"
                       f"INSERT INTO `{MARKER}` (id) VALUES (1);", password=root_password, database=DATABASE)
            atomic_json(DEV / "bootstrap-complete.json", {"database": DATABASE, "inputs": hashes, "completed": True})
            imported = True
        elif not marker_exists:
            raise DevError("Database is non-empty without this manager's completed-bootstrap marker; imports skipped. "
                           "Inspect the existing database; no tables were deleted or overwritten")
        elif self.mysql(f"SELECT COUNT(*) FROM `{MARKER}` WHERE id=1;", password=root_password, database=DATABASE) != "1":
            raise DevError("Bootstrap completion marker is invalid; existing database left untouched")
        else:
            completed = self.read_json(DEV / "bootstrap-complete.json", {})
            if completed.get("inputs") != hashes:
                print("Bootstrap inputs changed or the local record is absent; existing database was not re-imported.", flush=True)

        app_password = self.credentials["mysql_app_password"]
        sql = []
        for host in ["127.0.0.1", "localhost"]:
            sql += [f"CREATE USER IF NOT EXISTS '{APP_USER}'@'{host}' IDENTIFIED BY '{app_password}';",
                    f"ALTER USER '{APP_USER}'@'{host}' IDENTIFIED BY '{app_password}';",
                    f"GRANT ALL PRIVILEGES ON `{DATABASE}`.* TO '{APP_USER}'@'{host}';"]
        self.mysql("\n".join(sql), password=root_password)
        if self.records["mysql"].get("bootstrap"):
            self.stop_one("mysql")
        self.start_mysql(bootstrap=False)
        self.mysql("SELECT 1;", password=app_password, database=DATABASE, tcp=True, user=APP_USER)
        print("MySQL ready on 127.0.0.1:13306; " + ("bootstrap imported." if imported else "existing bootstrap reused."), flush=True)

    def start_redis(self) -> None:
        executable = self.binary("redis-server")
        self.binary("redis-cli")
        (DATA / "redis").mkdir(parents=True, exist_ok=True)
        config = DEV / "redis.conf"
        private_text(config, "\n".join([
            "bind 127.0.0.1", "port 16379", "protected-mode yes", "daemonize no",
            f'dir "{DATA / "redis"}"', "appendonly yes", "appendfsync everysec", 'save ""',
            f'pidfile "{DEV / "run/redis.pid"}"', f'logfile "{LOGS / "redis.log"}"',
            f"requirepass {self.credentials['redis_password']}", "",
        ]))
        self.spawn("redis", [executable, config])

        def ping() -> bool:
            environment = self.child_environment()
            environment["REDISCLI_AUTH"] = self.credentials["redis_password"]
            try:
                return self.run([self.binary("redis-cli"), "--no-auth-warning", "-h", "127.0.0.1", "-p", "16379", "PING"],
                                environment, timeout=5) == "PONG"
            except DevError:
                return False
        self.wait("redis", ping, 20)

    def start(self) -> None:
        # Resolve all required artifacts before starting any additional service.
        java = self.binary("java")
        self.binary("redis-server")
        self.binary("redis-cli")
        if not PROFILE.is_file() or not JAR.is_file() or not ASSETS.is_dir():
            raise DevError("Profile, backend JAR, or assets are missing. Generate assets and run build before start")
        self.initialize()
        self.start_redis()
        self.spawn("assets", [sys.executable, "-m", "http.server", "48081", "--bind", "127.0.0.1", "--directory", ASSETS])
        self.wait("assets", lambda: http_status(48081).get("httpStatus") == 200, 15)
        environment = self.child_environment()
        environment.update({"NAVIO_DB_USER": APP_USER, "NAVIO_DB_PASSWORD": self.credentials["mysql_app_password"],
                            "NAVIO_REDIS_PASSWORD": self.credentials["redis_password"], "NAVIO_DEV_HOME": str(DEV)})
        self.spawn("backend", [java, f"-Duser.home={DEV / 'tool-home'}", "-Xms256m", "-Xmx1536m", "-jar", JAR,
                               "--spring.profiles.active=navio-local",
                               f"--spring.config.additional-location=file:{PROFILE}"], environment)

        def healthy() -> bool:
            health = backend_readiness()
            return (health.get("httpStatus") == 200 and health.get("businessCode") == 0
                    and health.get("templateReady") is True)
        self.wait("backend", healthy, 240)
        print("All four managed services passed readiness checks on 127.0.0.1.", flush=True)
        self.status()

    def stop(self) -> None:
        self.directories()
        failures = []
        for name in ["backend", "assets", "redis", "mysql", "maven-cache"]:
            try:
                self.stop_one(name)
                print(f"{name}: stopped or already stopped", flush=True)
            except (DevError, OSError) as error:
                failures.append(f"{name}: {self.redact(str(error))}")
        if failures:
            raise DevError("; ".join(failures))

    def status(self) -> None:
        result = {}
        for name, port in PORTS.items():
            record = self.records.get(name, {})
            info = process_info(record.get("pid", 0)) if isinstance(record, dict) else None
            verified = bool(owned_process(name, info) and info["started"] == record.get("started"))
            item = {"host": "127.0.0.1", "port": port, "portReachable": port_open(port),
                    "ownedProcessVerified": verified, "pid": info["pid"] if verified else None}
            if name in ["assets", "backend", "maven-cache"]:
                item["http"] = backend_readiness() if name == "backend" else http_status(port, "/")
            result[name] = item
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

    def start_maven_cache(self) -> None:
        if not MAVEN_CACHE.is_file():
            raise DevError(f"Maven cache service is missing: {MAVEN_CACHE}")
        self.spawn("maven-cache", [sys.executable, MAVEN_CACHE])
        self.wait("maven-cache", lambda: http_status(18082).get("httpStatus") == 200, 10)

    def build(self) -> None:
        self.directories()
        java, mvn = self.binary("java"), self.binary("mvn")
        environment = self.child_environment()
        environment.update({"JAVA_HOME": str(java.parent.parent), "MAVEN_SKIP_RC": "true",
                            "MAVEN_USER_HOME": str(DEV / "tool-home/m2"),
                            "MAVEN_OPTS": f"-Duser.home={DEV / 'tool-home'} -Xmx2048m"})
        settings = DEV / "settings.xml"
        if not settings.is_file():
            raise DevError(f"Prepared Maven settings are missing: {settings}; no settings file was overwritten")
        self.start_maven_cache()
        logfile = LOGS / "maven-build.log"
        command = [mvn, "-B", "-ntp", "-T", "4", "-s", settings, "--global-settings", settings,
                   f"-Dmaven.repo.local={RUNTIME / 'maven-repository'}",
                   "-Daether.connector.connectTimeout=10000", "-Daether.connector.requestTimeout=90000",
                   "-Daether.transport.http.connectTimeout=10000", "-Daether.transport.http.requestTimeout=90000",
                   "-Daether.transport.http.retryHandler.count=1",
                   "-Dmaven.test.skip=true", "-pl", "yudao-server", "-am", "package"]
        print(f"Building backend; output: {logfile}", flush=True)
        with logfile.open("ab", buffering=0) as output:
            result = subprocess.run([str(p) for p in command], cwd=ROOT, env=environment,
                                    stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, check=False)
        if result.returncode != 0 or not JAR.is_file():
            raise DevError(f"Maven build failed or JAR is missing; see {logfile}")
        print(f"Backend build completed: {JAR}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "start", "stop", "status", "build"])
    args = parser.parse_args()
    os.umask(0o077)
    manager = None
    try:
        manager = Manager()
        if args.command == "status":
            manager.status()
            return 0
        DEV.mkdir(parents=True, exist_ok=True)
        with (DEV / "manager.lock").open("a") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DevError("Another local manager operation is running; try again after it finishes")
            manager.records = manager.read_json(STATE, {})
            {"init": manager.initialize, "start": manager.start, "stop": manager.stop, "build": manager.build}[args.command]()
        return 0
    except (DevError, OSError) as error:
        print("ERROR: " + (manager.redact(str(error)) if manager else str(error)), file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Existing data was preserved; use status to inspect any started services.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
