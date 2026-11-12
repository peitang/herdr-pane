#!/usr/bin/env python3
"""Select an existing local or SSH Herdr agent without changing server state."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import unicodedata
from urllib.parse import urlsplit


class PaneError(Exception):
    """An expected discovery, validation or connection failure."""


@dataclass(frozen=True)
class Source:
    profile_id: object = None
    label: str = "local"
    target: str = ""
    session: str = "目前 session"

    def prefix(self):
        return ["--machine", self.profile_id] if self.profile_id else []


@dataclass(frozen=True)
class AgentRow:
    source: Source
    pane_id: str
    terminal_id: str
    kind: str
    name: str
    status: str
    cwd: str


LOCAL = Source()
IDENTIFIER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9:_-]*\Z")
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
SSH_TARGET = re.compile(
    r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?"
    r"(?:\[[A-Fa-f0-9:.%]+\]|[A-Za-z0-9_][A-Za-z0-9_.-]*)\Z"
)
ANSI_ESCAPE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")


def display_text(value):
    """Render untrusted labels as one line, without terminal/bidi controls."""
    text = ANSI_ESCAPE.sub("", str(value or ""))
    return "".join(" " if unicodedata.category(c).startswith("C") else c for c in text)


def validate_identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise PaneError("Herdr 回傳的識別碼格式不正確")
    return value


def validate_session(value):
    if not isinstance(value, str) or not SESSION.fullmatch(value):
        raise PaneError("Session 請使用英數字、點、底線或連字號，並以英數字開頭")
    return value


def validate_target(value):
    if not isinstance(value, str) or not value:
        raise PaneError("請提供 SSH 別名或 user@host")
    candidate = value
    if value.startswith("ssh://"):
        try:
            parsed = urlsplit(value)
            if parsed.path or parsed.query or parsed.fragment or parsed.password is not None:
                raise ValueError()
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError()
            host = parsed.hostname or ""
            if ":" in host:
                host = "[" + host + "]"
            candidate = ((parsed.username + "@") if parsed.username else "") + host
        except ValueError as error:
            raise PaneError("SSH URL 格式不正確") from error
    elif "[" in value or "]" in value:
        raise PaneError("IPv6 請使用 ssh://user@[address] 格式，或先設定 SSH 別名")
    if not SSH_TARGET.fullmatch(candidate) or any(c.isspace() for c in value):
        raise PaneError("SSH 位置格式不支援；請使用 SSH 別名、user@host 或 ssh://user@host:port")
    return value


def parse_sources(data):
    if not isinstance(data, list):
        raise PaneError("機器清單不是預期的 JSON 陣列")
    sources, errors, seen = [], [], set()
    for index, profile in enumerate(data, 1):
        try:
            if not isinstance(profile, dict) or not isinstance(profile.get("enabled"), bool):
                raise PaneError("缺少明確的啟用狀態")
            if not profile["enabled"]:
                continue
            profile_id = validate_identifier(profile.get("id"))
            if profile_id in seen:
                raise PaneError("重複的機器識別碼")
            seen.add(profile_id)
            sources.append(Source(
                profile_id, str(profile.get("label") or profile_id),
                validate_target(profile.get("target")),
                validate_session(profile.get("session")),
            ))
        except PaneError as error:
            errors.append("遠端設定 #{}：{}".format(index, error))
    return sorted(sources, key=lambda source: (source.label, source.profile_id)), errors


def parse_agents(data, source):
    try:
        agents = data["result"]["agents"]
        if not isinstance(agents, list):
            raise TypeError()
    except (KeyError, TypeError):
        raise PaneError("Agent 清單缺少 result.agents") from None
    rows, seen = [], set()
    for agent in agents:
        if not isinstance(agent, dict):
            raise PaneError("Agent 清單含無效項目")
        kind = agent.get("agent")
        if kind is None or kind in ("", "shell", "none"):
            continue
        if not isinstance(kind, str):
            raise PaneError("Agent 類型格式不正確")
        pane_id = validate_identifier(agent.get("pane_id"))
        terminal_id = validate_identifier(agent.get("terminal_id"))
        if pane_id in seen:
            raise PaneError("Agent 清單出現重複 pane")
        seen.add(pane_id)
        rows.append(AgentRow(
            source, pane_id, terminal_id, kind,
            str(agent.get("name") or pane_id),
            str(agent.get("agent_status") or "unknown"),
            str(agent.get("cwd") or "—"),
        ))
    return sorted(rows, key=lambda row: row.pane_id)


class QueryRunner:
    """Bound query time and terminate only subprocess groups created here."""

    def __init__(self, herdr, timeout):
        self.herdr = herdr
        self.timeout = timeout
        self.active = set()
        self.lock = threading.Lock()
        self.cancelled = False

    @staticmethod
    def kill(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    @classmethod
    def stop(cls, process):
        cls.kill(process)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def error_code(error_file):
        known = {
            "server_not_running", "agent_not_found", "terminal_not_found",
            "machine_not_found", "machine_disabled", "protocol_incompatible",
            "endpoint_incompatible", "permission_denied",
        }
        try:
            error_file.seek(0)
            code = json.loads(error_file.read(65536))["error"]["code"]
            return code if isinstance(code, str) and code in known else ""
        except (ValueError, KeyError, TypeError):
            return ""

    def cancel(self):
        with self.lock:
            self.cancelled = True
            for process in self.active:
                self.kill(process)

    def __call__(self, args):
        # Anonymous files avoid waiting for EOF from detached SSH descendants.
        # They are unlinked, private, and never retained as debug logs.
        with tempfile.TemporaryFile() as output_file, tempfile.TemporaryFile() as error_file:
            with self.lock:
                if self.cancelled:
                    raise PaneError("查詢已取消")
                try:
                    process = subprocess.Popen(
                        [self.herdr] + args, stdin=subprocess.DEVNULL,
                        stdout=output_file, stderr=error_file, start_new_session=True,
                    )
                except OSError as error:
                    raise PaneError("無法執行 Herdr") from error
                self.active.add(process)
            try:
                try:
                    process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    self.stop(process)
                    raise PaneError("查詢逾時；請確認主機、SSH 驗證及 Herdr server") from None
                except BaseException:
                    self.stop(process)
                    raise
                if process.returncode:
                    code = self.error_code(error_file)
                    detail = ("；" + code) if code else ""
                    raise PaneError("查詢失敗（exit {}{}）；請確認 Herdr server／SSH 連線".format(process.returncode, detail))
                output_file.seek(0)
                output = output_file.read(8 * 1024 * 1024 + 1)
                if len(output) > 8 * 1024 * 1024:
                    raise PaneError("Herdr 回應超過允許大小")
                try:
                    return json.loads(output)
                except (ValueError, UnicodeError):
                    raise PaneError("Herdr 沒有回傳有效 JSON") from None
            finally:
                with self.lock:
                    self.active.discard(process)


def inventory(query):
    errors = []
    try:
        sources, errors = parse_sources(query(["machine", "list", "--json"]))
    except PaneError as error:
        sources = []
        errors.append("遠端設定：{}".format(error))
    all_sources = [LOCAL] + sources
    executor = ThreadPoolExecutor(max_workers=min(8, len(all_sources)))
    futures = [(source, executor.submit(query, source.prefix() + ["agent", "list"]))
               for source in all_sources]
    rows = []
    try:
        for source, future in futures:
            try:
                rows.extend(parse_agents(future.result(), source))
            except PaneError as error:
                errors.append("{}：{}".format(display_text(source.label), error))
    except BaseException:
        if hasattr(query, "cancel"):
            query.cancel()
        for _, future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True)
    return rows, errors, len(sources)


def revalidate(row, query):
    if row.source.profile_id:
        sources, _ = parse_sources(query(["machine", "list", "--json"]))
        if row.source not in sources:
            raise PaneError("遠端設定已變更、停用或刪除，請重新選號")
    current = parse_agents(query(row.source.prefix() + ["agent", "list"]), row.source)
    if not any((item.pane_id, item.terminal_id, item.kind, item.name) ==
               (row.pane_id, row.terminal_id, row.kind, row.name) for item in current):
        raise PaneError("目標已離開或被替換，請重新選號")


def caller_pids():
    """Find the actual process ancestors; inherited Herdr IDs can be stale."""
    ancestors = {os.getpid()}
    try:
        output = subprocess.check_output(
            ["ps", "-ax", "-o", "pid=,ppid="], text=True, timeout=2,
        )
        parents = {}
        for line in output.splitlines():
            pid, parent = line.split()
            parents[int(pid)] = int(parent)
        pid = os.getpid()
        while parents.get(pid, 0) > 1 and parents[pid] not in ancestors:
            pid = parents[pid]
            ancestors.add(pid)
    except (OSError, ValueError, subprocess.SubprocessError):
        # Foreground process membership can still positively identify this PID.
        pass
    return ancestors


def is_own_terminal(row, query, ancestors):
    if row.source.profile_id or not ancestors:
        return False
    try:
        info = query(["pane", "process-info", "--pane", row.pane_id])["result"]["process_info"]
        shell_pid = info["shell_pid"]
        processes = info["foreground_processes"]
        if not isinstance(shell_pid, int) or shell_pid <= 0 or not isinstance(processes, list):
            raise ValueError()
        pids = {shell_pid}
        pids.update(process["pid"] for process in processes)
        return bool(pids & ancestors)
    except (KeyError, TypeError, ValueError):
        raise PaneError("無法核對本機終端的程序身分；請刷新後重試") from None


def exclude_own_terminal(rows, query, ancestors):
    """Keep uncertain rows visible; selection will verify them again and fail closed."""
    if not ancestors:
        return rows
    def keep(row):
        try:
            return not is_own_terminal(row, query, ancestors)
        except PaneError:
            return True
    executor = ThreadPoolExecutor(max_workers=min(8, max(1, len(rows))))
    try:
        retained = list(executor.map(keep, rows))
    except BaseException:
        if hasattr(query, "cancel"):
            query.cancel()
        raise
    finally:
        executor.shutdown(wait=True)
    return [row for row, keep_row in zip(rows, retained) if keep_row]


def attach_command(row, herdr, ssh):
    validate_identifier(row.terminal_id)
    if not row.source.profile_id:
        return [herdr, "terminal", "attach", row.terminal_id]
    validate_target(row.source.target)
    validate_session(row.source.session)
    # This fixed POSIX script is interpreted remotely; no user value is code.
    # Unlike `herdr --remote`, terminal attach never prepares/restarts a server.
    script = (
        'herdr_bin=$(command -v herdr 2>/dev/null)\n'
        'if [ -z "$herdr_bin" ]; then\n'
        '    for candidate in "$HOME/.local/bin/herdr" /opt/homebrew/bin/herdr '
        '/usr/local/bin/herdr "$HOME/.nix-profile/bin/herdr"; do\n'
        '        if [ -x "$candidate" ]; then herdr_bin=$candidate; break; fi\n'
        '    done\n'
        'fi\n'
        'if [ -z "$herdr_bin" ]; then printf "%s\\n" "herdr-pane: remote Herdr not found" >&2; exit 127; fi\n'
        'unset HERDR_SOCKET_PATH HERDR_SESSION HERDR_ENV HERDR_PANE_ID\n'
        '"$herdr_bin" ' + shlex.join(["--session", row.source.session, "agent", "list"]) +
        ' >/dev/null || exit 1\n'
        'exec "$herdr_bin" ' + shlex.join([
            "--session", row.source.session, "terminal", "attach", row.terminal_id,
        ])
    )
    return [ssh, "-t", "--", row.source.target, "sh -c " + shlex.quote(script)]


def add_remote(target, session, herdr, run):
    validate_target(target)
    validate_session(session)
    return run([herdr, "machine", "add", target, "--remote-session", session])


def saved_profiles(query):
    """Read removable profiles, including disabled or unsupported SSH targets."""
    data = query(["machine", "list", "--json"])
    if not isinstance(data, list):
        raise PaneError("機器清單不是預期的 JSON 陣列")
    profiles, seen = [], set()
    for item in data:
        if not isinstance(item, dict):
            raise PaneError("機器清單含無效項目")
        profile_id = validate_identifier(item.get("id"))
        if profile_id in seen:
            raise PaneError("機器清單含重複識別碼，無法安全移除")
        seen.add(profile_id)
        profiles.append({key: item.get(key) for key in (
            "id", "label", "target", "session", "enabled",
        )})
    return sorted(profiles, key=lambda item: (str(item["label"] or ""), item["id"]))


def remove_remote(profile_id, herdr, query, run):
    if profile_id:
        validate_identifier(profile_id)
    profiles = saved_profiles(query)
    if profile_id:
        selected = next((item for item in profiles if item["id"] == profile_id), None)
        if selected is None:
            raise PaneError("找不到此 PROFILE_ID；請用 --remove-remote 選號，不接受主機標籤")
    else:
        if not profiles:
            print("沒有儲存的遠端連線。")
            return 0
        print("\n可移除的遠端連線（包含已停用）：")
        for index, item in enumerate(profiles, 1):
            print("{:>3}  {}  |  {}  |  {} / {}".format(
                index, item["id"], display_text(item["label"]),
                display_text(item["target"]), display_text(item["session"]),
            ))
        while True:
            try:
                index = selection_index(input("選擇要移除的編號，Enter 取消："), len(profiles))
                break
            except PaneError as error:
                print(error)
        if index is None:
            return 0
        selected = profiles[index]
    state = "啟用" if selected["enabled"] is True else "停用" if selected["enabled"] is False else "未知"
    print("\n移除 {} | {} | {} / {} [{}]".format(
        selected["id"], display_text(selected["label"]), display_text(selected["target"]),
        display_text(selected["session"]), state,
    ))
    print("只移除本機儲存的連線；本機 Herdr client 會與它斷線，遠端 session／agent 繼續執行。")
    print("之後需重新新增連線；暫時停用可用 herdr machine disable " + selected["id"])
    if input("確認移除？輸入 yes 確認，Enter 取消：").strip().lower() != "yes":
        print("已取消。")
        return 0
    if selected not in saved_profiles(query):
        raise PaneError("遠端設定已變更或刪除，請重新執行 --remove-remote 核對")
    result = run([herdr, "machine", "remove", selected["id"]])
    if result:
        raise PaneError("移除命令失敗（exit {}）；請檢查原生訊息".format(result))
    try:
        remaining = saved_profiles(query)
    except PaneError as error:
        raise PaneError("移除命令已執行，但無法確認結果；請用 herdr machine list --json 檢查") from error
    if any(item["id"] == selected["id"] for item in remaining):
        raise PaneError("移除後仍有此 PROFILE_ID；請用 herdr machine list --json 檢查")
    print("已移除連線 " + selected["id"] + "；遠端 session／agent 不受影響。")
    return 0


def selection_index(text, count):
    text = text.strip()
    if not text:
        return None
    if not re.fullmatch(r"[0-9]{1,8}", text) or not 1 <= int(text) <= count:
        raise PaneError("請輸入這次清單內的編號，或按 Enter 離開")
    return int(text) - 1


def print_inventory(rows, errors, remote_count):
    print("\nherdr-pane · 本機與遠端 agent\n")
    for index, row in enumerate(rows, 1):
        print("{:>3}  {} / {}  |  {} · {}  [{}]".format(
            index, display_text(row.source.label), display_text(row.source.session),
            display_text(row.kind), display_text(row.name), display_text(row.status),
        ))
        print("     " + display_text(row.cwd))
    if not rows:
        print("目前沒有可連線的 agent。請先在 Herdr session 啟動 agent，或稍後刷新。")
    for error in errors:
        print("! " + display_text(error))
    if not remote_count:
        print("\n新增遠端：herdr-pane --add-remote [SSH_TARGET]")


def find_herdr():
    found = shutil.which("herdr")
    if found:
        return found
    candidate = Path.home() / ".local/bin/herdr"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    raise PaneError("找不到 Herdr；請先安裝並將 herdr 加入 PATH")


def interactive_run(args):
    return subprocess.call(args)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="herdr-pane", description="列出本機與已設定遠端的 agent，選號接上原終端。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="遠端管理：\n  herdr-pane --remove-remote             選號並確認移除連線\n"
               "  herdr machine list --json              查詢 PROFILE_ID\n"
               "  herdr machine disable PROFILE_ID       暫時停用\n"
               "  herdr machine enable PROFILE_ID        重新啟用\n"
               "  herdr machine remove PROFILE_ID        原生移除指令\n"
               "移除或停用連線不會停止遠端 session／agent。",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("-l", "--list", action="store_true", help="只列清單，不接上終端")
    modes.add_argument("--add-remote", nargs="?", const="", metavar="SSH_TARGET", help="引導新增遠端後返回選單")
    modes.add_argument("--remove-remote", nargs="?", const="", metavar="PROFILE_ID", help="選號或指定 ID，確認後移除儲存的遠端連線")
    parser.add_argument("--remote-session", help="新增遠端時明確指定 session；未提供時詢問")
    parser.add_argument("--timeout", type=float, default=10, help="每個查詢的期限秒數（預設 10）")
    parser.add_argument("--version", action="version", version="herdr-pane 0.2.0")
    args = parser.parse_args(argv)
    if not 0.1 <= args.timeout <= 120:
        parser.error("--timeout 必須介於 0.1 與 120 秒")
    if args.remote_session is not None and args.add_remote is None:
        parser.error("--remote-session 必須配合 --add-remote")
    query = None
    try:
        herdr = find_herdr()
        if not args.list and not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise PaneError("請在互動終端執行；只看清單可使用 --list")
        if args.remove_remote is not None:
            query = QueryRunner(herdr, args.timeout)
            return remove_remote(args.remove_remote, herdr, query, interactive_run)
        if args.add_remote is not None:
            target = args.add_remote or input("SSH 別名或 user@host（Enter 取消）：").strip()
            if not target:
                return 0
            validate_target(target)
            session = args.remote_session or input("遠端 session 名稱 [default]：").strip() or "default"
            validate_session(session)
            print("接下來使用 Herdr 原生設定；請自行確認 SSH 身分與安裝／更新提示。")
            print("不存在的 session 會被建立並啟動；請確認名稱，已有的 session 也可能啟動背景 server。")
            if add_remote(target, session, herdr, interactive_run):
                print("遠端設定未完成；返回既有清單。")
        query = QueryRunner(herdr, args.timeout)
        ancestors = caller_pids()
        while True:
            if not args.list:
                print("正在查詢本機與已啟用遠端…", flush=True)
            rows, errors, count = inventory(query)
            rows = exclude_own_terminal(rows, query, ancestors)
            print_inventory(rows, errors, count)
            if args.list:
                return 0 if rows or not errors else 1
            while True:
                answer = input("\n輸入編號連線，r 刷新，Enter 離開：").strip()
                if answer.lower() == "r":
                    break
                try:
                    index = selection_index(answer, len(rows))
                except PaneError as error:
                    print(error)
                    continue
                if index is None:
                    return 0
                row = rows[index]
                try:
                    revalidate(row, query)
                    if is_own_terminal(row, query, ancestors):
                        raise PaneError("不能接上正在執行 herdr-pane 的終端，請選其他 agent")
                    ssh = shutil.which("ssh") if row.source.profile_id else ""
                    if row.source.profile_id and not ssh:
                        raise PaneError("找不到 OpenSSH client：ssh")
                    print("接上 {} / {} / {}。Ctrl+B 後按 Q 離開；巢狀 Herdr 可能需先傳送內層前綴。".format(
                        display_text(row.source.label), display_text(row.source.session), display_text(row.name),
                    ), flush=True)
                    result = interactive_run(attach_command(row, herdr, ssh))
                    if result == 0:
                        return 0
                    print("連線已結束（exit {}）。請確認上述 Herdr／SSH 訊息後重新選號；不自動重連或接管。".format(result))
                except PaneError as error:
                    print(error)
                break
    except (KeyboardInterrupt, EOFError):
        if query:
            query.cancel()
        print("\n已取消。", file=sys.stderr)
        return 130
    except (PaneError, OSError) as error:
        print("herdr-pane: " + display_text(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
