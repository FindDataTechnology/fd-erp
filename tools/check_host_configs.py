#!/usr/bin/env python3
"""宿主机边缘配置的守卫：拒绝"单站点 bind 抢占共享监听地址"。

为什么需要它
------------
Caddy 按**监听地址集**分组 server，不是按端口。若某一个站点块写了
`bind 172.22.222.1`，Caddy 会为这组地址单开一个 server，并把
`172.22.222.1:8080` 从共享的 `:8080` server 里夺走（更具体的地址胜出）。
雷池的转发目标就是这个地址，于是其余所有 `*.finddatatech.cloud` 落到只有
一条路由的 server 上，host 匹配不上 → **空 200**（`http=200 size=0`）。
状态码巡检看不见它；只有"旁证另一个域名有非零 body"才看得见。

2026-11-11 这行被加进去两次（第二次是"配置回仓版本化"顺手补回，验收只验了
erp 自己 200，于是假绿上线），平台整站白了两次。

两道检查
--------
- 默认（本地）：扫 `deploy/host/*.conf`。这些片段会被**追加**到一个已经有很多
  :8080 站点的 Caddyfile 里，片段自身无法证明"地址集统一"，所以这里对共享端口上的
  `bind` 一律拒绝；真要用，得在同一段落里写 `# bind-uniform-ok: <理由>`。
- `--live`：连上边缘读线上 Caddyfile，按端口分组算每个站点块的有效地址集，
  集合不一致就是分叉（这才是根因本身；本地片段只是它的来源之一）。

判据要能变红：`--self-test` 用内嵌正反例各跑一遍，任一方向不对就退出 2。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HOST_DIR = Path(__file__).resolve().parents[1] / "deploy" / "host"
EDGE = "root@<edge-host>"
CADDYFILE = "/etc/caddy/Caddyfile"

#: 这些绑定写法等价于"所有网卡"，不算收窄，因此不构成地址集分叉
_WILDCARD = {"", "0.0.0.0", "::", "[::]", "*"}

_ADDR_RE = re.compile(r"^(?:(?P<scheme>https?)://)?(?P<rest>.+)$")
_PORT_RE = re.compile(r":(?P<port>\d+)$")
_OK_MARK = re.compile(r"#\s*bind-uniform-ok:\s*(?P<reason>.+)")


def _strip_comment(line: str) -> str:
    """去掉行尾注释。配置里没有带引号的 #，先按最简规则处理并保持可读。"""
    idx = line.find("#")
    return line if idx < 0 else line[:idx]


def _split_addresses(header: str) -> list[str]:
    return [a for a in re.split(r"[,\s]+", header.strip()) if a]


def _port_of(addr: str) -> tuple[str, int]:
    """返回 (主机部分, 端口)。默认端口按 scheme 推断：http→80、https→443。"""
    scheme = "https" if addr.startswith("https://") else "http"
    body = addr.split("://", 1)[-1]
    m = _PORT_RE.search(body)
    if m:
        return body[: m.start()], int(m.group("port"))
    return body, 80 if scheme == "http" else 443


def parse_sites(text: str) -> list[dict]:
    """从 Caddyfile 文本里抽出站点块。

    返回每项：{"header": 原始头, "addresses": [原始地址], "ports": {port},
               "bind": [bind 地址] or None, "line": 起始行号, "lines": 块内文本}
    只处理一层嵌套（site block → directive），足够覆盖宿主机的用法。
    """
    sites: list[dict] = []
    depth = 0
    pending: list[str] = []      # 还没看到 { 的站点头（地址可能跨行）
    pending_line = 0
    current: dict | None = None
    for no, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if depth == 0:
            if stripped == "{":
                continue          # 全局 options 块，与监听分组无关
            pending.append(stripped)
            if pending_line == 0:
                pending_line = no
            if stripped.endswith("{"):
                header = " ".join(pending)[:-1].strip()
                pending, pending_line = [], 0
                current = {"header": header, "addresses": _split_addresses(header),
                           "bind": None, "line": no, "lines": []}
                sites.append(current)
                depth = 1
            continue

        # depth >= 1：块内
        if current is not None:
            current["lines"].append(stripped)
        if stripped.startswith("bind ") and current is not None and current["bind"] is None:
            current["bind"] = _split_addresses(stripped[len("bind "):])
        depth += stripped.count("{") - stripped.count("}")
        if depth <= 0:
            depth = 0
            current = None
    for site in sites:
        ports: set[int] = set()
        for a in site["addresses"]:
            if a.startswith(":"):
                ports.add(int(a[1:]))
            else:
                ports.add(_port_of(a)[1])
        site["ports"] = ports
    return sites


def _effective_set(site: dict, port: int) -> frozenset[str]:
    """某站点在某端口上的有效监听地址集（用于判断是否同一个 server）。

    `bind` 不带端口时沿用站点自己的端口；带端口时只在端口匹配时计入。
    空集表示该站点在这个端口上没有监听。
    """
    if not site["bind"]:
        return frozenset({"*"})
    out: set[str] = set()
    for addr in site["bind"]:
        body = addr.split("://", 1)[-1]
        m = _PORT_RE.search(body)
        host = body[: m.start()] if m else body
        if m and int(m.group("port")) != port:
            continue
        out.add("*" if host in _WILDCARD else host)
    return frozenset(out)


def check_sites(sites: list[dict], *, source: str) -> list[dict]:
    """按端口分组，找出地址集分叉。"""
    problems: list[dict] = []
    by_port: dict[int, list[dict]] = {}
    for site in sites:
        for port in site["ports"]:
            by_port.setdefault(port, []).append(site)
    for port, group in sorted(by_port.items()):
        # 只算真正在这个端口上监听的站点（bind 带了别的端口的不算）
        live = [s for s in group if _effective_set(s, port)]
        if len(live) < 2:
            continue
        sets = {_effective_set(s, port) for s in live}
        if len(sets) > 1:
            detail = "；".join(
                f"{s['header']} → {sorted(_effective_set(s, port))}" for s in live[:4]
            )
            problems.append({
                "code": "LISTEN_SET_SPLIT",
                "message": (f"{source}: :{port} 被分成了 {len(sets)} 个 server"
                            f"（{detail}）。带 bind 的站点会把这组地址从共享 server 里抢走，"
                            f"其余站点的请求将得到空 200。删掉单站点 bind，或让所有 :{port} "
                            f"站点写同一组 bind。"),
            })
    return problems


def check_fragments(host_dir: Path = HOST_DIR) -> list[dict]:
    """本地片段：共享端口上的单站点 bind 一律拒绝（片段无法自证地址集统一）。"""
    problems: list[dict] = []
    files = sorted(host_dir.glob("*.conf"))
    if not files:
        return [{"code": "NO_FRAGMENTS", "message": f"{host_dir} 下没有 *.conf；闸没输入等于没闸"}]
    texts = {}
    for path in files:
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append({"code": "UNREADABLE", "message": f"{path.name}: {exc}"})
    all_sites: list[dict] = []
    for path, text in texts.items():
        all_sites.extend(parse_sites(text))

    # 哪些端口在语料里被多个站点共用（片段之间能看见的那部分）
    port_use: dict[int, int] = {}
    for site in all_sites:
        for port in site["ports"]:
            port_use[port] = port_use.get(port, 0) + 1
    # 边缘上已知共享的端口：线上还有几十个站点在这两个端口上，片段看不到
    known_shared = {80, 443, 8080}

    for path, text in texts.items():
        marker = _OK_MARK.search(text)
        if marker and str(marker.group("reason")).strip():
            continue
        for site in parse_sites(text):
            if not site["bind"]:
                continue
            risky = sorted(p for p in site["ports"]
                           if p in known_shared or port_use.get(p, 0) > 1)
            if not risky:
                continue
            problems.append({
                "code": "SINGLE_SITE_BIND",
                "message": (f"deploy/host/{path.name}:{site['line']} 给单个站点写了 bind "
                            f"{site['bind']}（端口 {risky}）。这段会被追加到共享的 Caddyfile，"
                            f"Caddy 会按该地址集单开 server，把地址从共享 server 里抢走 → "
                            f"其余站点空 200。删掉它，改用防火墙收口；"
                            f"确需保留则在文件里写 `# bind-uniform-ok: <理由>`。"),
            })
    # 片段整体也过一遍分叉检查：两个片段若在不同地址集上监听同一端口，同样是分叉
    problems.extend(check_sites(all_sites, source="deploy/host/*.conf"))
    return problems


def _read_live() -> str:
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", EDGE, f"cat {CADDYFILE}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "").strip() or f"ssh 失败（rc={proc.returncode}）")
    return proc.stdout


def check_live(text: str) -> list[dict]:
    problems = check_sites(parse_sites(text), source=f"{EDGE}:{CADDYFILE}")
    empty = [p for p in problems if p["code"] == "LISTEN_SET_SPLIT"]
    if not empty:
        # 地址集没问题时，再旁证一条共享 :8080 的邻居：分叉以外的静默故障也看得见
        probe = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{size_download}",
             "--max-time", "12", "https://lawbench.finddatatech.cloud/healthz"],
            capture_output=True, text=True,
        )
        out = (probe.stdout or "").strip().split()
        if len(out) == 2 and out[0] == "200" and out[1] != "0":
            return []
        problems.append({"code": "NEIGHBOR_UNHEALTHY",
                         "message": (f"邻居探针不健康：lawbench/healthz → {probe.stdout!r}。"
                                     f"空 200 或非 200 都说明共享 :8080 的其它站点没在正常应答。")})
    return problems


_SELF_OK = """
http://a.example:8080 {
	reverse_proxy 127.0.0.1:1
}
http://b.example:8080 {
	reverse_proxy 127.0.0.1:1
}
"""

_SELF_SPLIT = """
http://a.example:8080 {
	bind 172.22.222.1
	reverse_proxy 127.0.0.1:1
}
http://b.example:8080 {
	reverse_proxy 127.0.0.1:1
}
"""

_SELF_OTHER_PORT = """
http://a.example:8080 {
	reverse_proxy 127.0.0.1:1
}
http://b.example:8080 {
	reverse_proxy 127.0.0.1:1
}
http://<object-store-host>:9000 {
	bind <object-store-host>
	reverse_proxy 127.0.0.1:2
}
"""


def self_test() -> int:
    """正反例各跑一次：判据不能在做之前就已经是绿的。"""
    cases = [
        ("无 bind（健康）", _SELF_OK, 0),
        ("单站点 bind 抢地址（必须红）", _SELF_SPLIT, 1),
        ("不同端口上的 bind（合法）", _SELF_OTHER_PORT, 0),
    ]
    bad = 0
    for label, text, want in cases:
        got = len(check_sites(parse_sites(text), source=label))
        verdict = "PASS" if (got > 0) == (want > 0) else "FAIL"
        bad += verdict == "FAIL"
        print(f"  {verdict:<4} {label:<28} 命中 {got} 条")
    if bad:
        print("\n自检失败：判据两个方向都不对", file=sys.stderr)
        return 2
    print("\n自检通过：健康配置为 0 命中，抢地址配置必中")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="连上边缘校验线上 Caddyfile")
    ap.add_argument("--self-test", action="store_true", help="用内嵌正反例验证闸本身")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    problems = check_fragments()
    live_unknown = None
    if args.live:
        try:
            problems.extend(check_live(_read_live()))
        except RuntimeError as exc:
            # 连不上时**既不算通过也不算失败**：显式退出 2，由调用方记成 SKIP 并说明原因。
            # 这里判"绿"就是"没有输入时的绿灯"，比没有闸更糟。
            live_unknown = str(exc)

    for p in problems:
        print(f"  x [{p['code']}] {p['message']}")
    if problems:
        print("\n边缘配置：阻断")
        return 1
    if live_unknown:
        print(f"边缘配置：本地片段通过；线上未校验（{live_unknown}）")
        return 2
    print("边缘配置：通过（片段无单站点 bind" + ("，线上地址集未分叉" if args.live else "") + "）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
