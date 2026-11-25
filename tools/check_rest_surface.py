#!/usr/bin/env python3
"""REST 实现面 ↔ 声明契约 双向对拍闸（change: gate-rest-surface-against-contract）。

守的是**声明面失信**这一类事故：契约四份 `api-contract.md` 都写着「本契约全部端点与
MCP 工具面同源数据」，但此前没有任何闸核对这句话——2026-11-12 实测，两条新端点加进
`faces.py` 后测试全绿、各闸全绿、变更归档，契约表里却始终没有那两行。

三个方向都判红：

  1. 实现有、声明无   —— 新增端点必须同时补契约行（哪怕是如实 501 的端点，也要声明）；
  2. 声明有、实现无   —— 契约不得悬空；
  3. 白名单条目过期   —— 基础设施端点免检牌必须跟着路由走，改名/删除后要撤牌。

为什么用 AST 而不是手抄清单：`planned_surfaces.py` 已经因为同一理由选了 AST（手抄必腐化）。
本闸沿用它 `_routes` 的写法，不引入第二套解析。

**基础设施端点走代码内显式白名单**，不按路径前缀自动放行：前缀规则会静默吞掉未来任何以
`/health` 开头的业务端点；白名单每加一条都要写理由与声明出处，加的时候人会想一下。

解析到零行契约直接判红：零行不是「通过」，是解析器失效（表头被改、缩进变了、列顺序换了）。

退出码：0 通过 / 1 有漂移 / 2 输入缺失（兄弟仓不在场，非通过）。

用法：
    python3 tools/check_rest_surface.py
    python3 tools/check_rest_surface.py --api-dir <repo>/fd_erp_vertical_api \\
        --pagesets-dir <templates>/templates/supply-chain/pagesets
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

#: 工作区根（fd-erp/tools/check_rest_surface.py → parents[2]）。worktree 下兄弟仓不在场，
#: 于是走 SKIP 分支——缺输入与漂移是两件事，不混为一谈。
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_DIR = ROOT / "fd-erp-vertical-api" / "fd_erp_vertical_api"
DEFAULT_PAGESETS_DIR = (ROOT / "fd-erp-vertical-templates" / "templates" / "supply-chain"
                        / "pagesets")

#: **内部面**契约（没有页面集的服务端面）：与页面集契约同格式，只是所在的那一层
#: 不被覆盖矩阵度量（功能点对账表、域计数、已提交快照）。声明在这里而不是塞进
#: 某个页集契约：内部面没有页面，塞进去会改变一个封闭空间的度量。
# 店面公开面（change establish-ai-native-ecommerce-stack 0.4）：匿名可读，
# 故**不进**四张页面集表（那四张的前提是页面集授权 + 身份域）；
# 单独一份文件，逐条标身份要求（匿名路由必须写理由与声明出处）。
STOREFRONT_CONTRACT = (ROOT / "fd-erp-vertical-api" / "STOREFRONT-API.md",
                       "店面公开面契约")
# 交易协商面（change establish-ai-native-trade-discovery 2.x）：不是页面集、也不是匿名面，
# 故同样单立一份。混进四张页集表会改变那层「封闭空间」的度量（与店面同一理由）。
TRADE_CONTRACT = (ROOT / "fd-erp-vertical-api" / "TRADE-API.md",
                  "交易协商面契约")

INTERNAL_CONTRACT_FILES: tuple[tuple[Path, str], ...] = (
    (ROOT / "fd-erp-vertical-api" / "INTERNAL-API.md", "内部面契约"),
    # 仓管作业面（内部页集 supply-chain.wh）：单独一份文件。理由是同族但更窄——
    # fi 那份的字段承诺闸（tests/test_internal_api_field_promise.py）按 `fi` 前缀对齐
    # OpenAPI 路由，混进 wh 行会被判成「文档里有、代码里没有」的幽灵行。
    # 两面各按自己的前缀划人口，别让一份文件承载两个页集。
    (ROOT / "fd-erp-vertical-api" / "INTERNAL-WH-API.md", "仓管作业内部面契约"),
)

#: 店面契约的身份取值封闭集（见 STOREFRONT-API.md §0）
_STOREFRONT_IDENTITIES = ("匿名", "商家", "买家凭据")

#: 参与派生实现的文件（faces 是四个页面集的业务面，app 是服务级与少量 UE 面，
#: storefront 是店面公开面）。漏登记一个文件 = 那个文件的端点全被判成「未声明」以外的
#: 另一种错：它压根不进实现面，于是契约行会被误判为悬空。
#: 扫**整个 api 包目录**，不手抄文件名清单。手抄清单的腐化形态是静默的：新增一个
#: `trade.py` 后，它声明的路由不被派生 ⇒ 契约里写了反而判「悬空」（2026-11-25 实测）。
#: 仅排除兼容用的 `__init__.py`（不挂路由）。
API_FILES_EXCLUDE = {"__init__.py"}


def _api_files(api_dir: Path) -> list[str]:
    return sorted(p.name for p in api_dir.glob("*.py")
                  if p.name not in API_FILES_EXCLUDE)

#: 声明表行：`| GET | `/erp/...` | ... |`
ROW_RE = re.compile(r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`")
PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")

#: 基础设施端点白名单：不进业务契约，但必须有理由 + 声明出处。
#: 反向核对：这里登记的路由若已不存在 → 判红（撤牌）。
INFRA_ENDPOINTS: tuple[dict[str, str], ...] = (
    {
        "method": "GET", "path": "/health",
        "why": "进程存活探针（容器 liveness/readiness 用），不属于任何页面集的业务面",
        "declared_at": "fd-erp-vertical-api/README.md「访问日志」节（探针路径列为调试可见项）",
    },
    {
        "method": "GET", "path": "/healthz",
        "why": "k8s 风格健康探针别名，同上，不承载业务语义",
        "declared_at": "fd-erp-vertical-api/README.md「访问日志」节",
    },
    {
        "method": "GET", "path": "/erp/supply-chain/v1/pagesets",
        "why": "页面集授权形状查询：给客户端解析 key/grant 用，不属于四个页面集任一方的业务面",
        "declared_at": "fd-erp-vertical-api/README.md「页面集授权形状」节",
    },
)


def norm(path: str) -> str:
    """占位符规范化：`{request_id}` 与 `{requestId}` 是同一路由。

    只做这一条归一（把 `{...}` 换成 `{}`）。不做大小写折叠、不做尾斜杠折叠——那会把真正
    不同的路径判成相同，闸就失去了意义。
    """
    return PLACEHOLDER_RE.sub("{}", path.strip())


def _routes_of(src: str, fname: str) -> list[tuple[str, str, str]]:
    """该文件里声明的路由：(METHOD, 原始路径, 文件)。"""
    out: list[tuple[str, str, str]] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:  # 语法错要如实报，不能静默当零条
        raise SystemExit(f"FAIL: 无法解析 {fname}：{exc}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            attr = getattr(dec.func, "attr", "")
            if attr not in ("get", "post", "put", "patch", "delete"):
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(
                    dec.args[0].value, str):
                out.append((attr.upper(), dec.args[0].value, fname))
    return out


def derive_code(api_dir: Path) -> tuple[dict[tuple[str, str], tuple[str, str]], list[str]]:
    """实现端点集合 + 重复路由问题。

    键是 (method, 规范化路径)；值是 (原始路径, 文件)。同一路由被两个处理器抢注是 bug，
    单独报出来（FastAPI 会静默保留先注册的那个）。
    """
    code: dict[tuple[str, str], tuple[str, str]] = {}
    dupes: list[str] = []
    for fname in _api_files(api_dir):
        path = api_dir / fname
        if not path.is_file():
            continue
        for method, raw, src in _routes_of(path.read_text(encoding="utf-8"), fname):
            key = (method, norm(raw))
            if key in code:
                dupes.append(f"{method} {norm(raw)} 在 {code[key][1]} 与 {src} 重复注册")
                continue
            code[key] = (raw, src)
    return code, dupes


def derive_declared(pagesets_dir: Path) -> tuple[dict[tuple[str, str], tuple[str, str]],
                                                 list[str]]:
    """契约表里的端点集合 + 解析失效问题（零行 = 解析失效，判红）。"""
    declared: dict[tuple[str, str], tuple[str, str]] = {}
    problems: list[str] = []
    files = sorted(pagesets_dir.glob("*/api-contract.md"))
    if not files:
        problems.append(f"契约文件一个都没找到：{pagesets_dir}/*/api-contract.md")
        return declared, problems
    for f in files:
        rows = 0
        for line in f.read_text(encoding="utf-8").splitlines():
            m = ROW_RE.match(line)
            if not m:
                continue
            rows += 1
            method, raw = m.group(1), m.group(2)
            key = (method, norm(raw))
            if key in declared:
                problems.append(f"{method} {norm(raw)} 在两份契约里重复声明："
                                f"{declared[key][1]} 与 {f.parent.name}")
                continue
            declared[key] = (raw, f.parent.name)
        if rows == 0:
            problems.append(f"{f.parent.name}/api-contract.md 解析到 0 条端点——表行格式变了？"
                            "（零行不是通过，是解析失效）")
    return declared, problems


def _derive_declared_from_files(files: list[tuple[Path, str]],
                                ) -> tuple[dict[tuple[str, str], tuple[str, str]],
                                           list[str]]:
    """从任意契约文件（页面集契约或内部面契约）解析端点表。"""
    declared: dict[tuple[str, str], tuple[str, str]] = {}
    problems: list[str] = []
    for path, label in files:
        if not path.is_file():
            problems.append(f"{label} 文件不存在：{path}——声明面缺一份，端点就没了出处")
            continue
        rows = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            m = ROW_RE.match(line)
            if not m:
                continue
            rows += 1
            method, raw = m.group(1), m.group(2)
            key = (method, norm(raw))
            if key in declared:
                problems.append(f"{method} {norm(raw)} 在两份契约里重复声明："
                                f"{declared[key][1]} 与 {label}")
                continue
            declared[key] = (raw, label)
        if rows == 0:
            problems.append(f"{label} 解析到 0 条端点——表行格式变了？"
                            "（零行不是通过，是解析失效）")
    return declared, problems


def check_storefront_identity(path: Path) -> list[str]:
    """店面契约表每行必须标身份要求，且取值在封闭集内。

    这条守的是「匿名是显式决定」：匿名路由如果只是没人给它加身份头，那它跟
    「忘了加鉴权」长得一模一样。表格强制写出来，人才会想一次。
    """
    problems: list[str] = []
    if not path.is_file():
        return [f"店面契约文件不存在：{path}"]
    rows = 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not ROW_RE.match(line):
            continue
        rows += 1
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        identity = cells[-1] if cells else ""
        if identity not in _STOREFRONT_IDENTITIES:
            problems.append(
                f"{path.name}:{i} 身份列={identity!r} 不在 {_STOREFRONT_IDENTITIES}——"
                f"店面每行必须标身份要求（匿名/商家/买家凭据）")
    if rows == 0:
        problems.append(f"{path.name} 解析到 0 条端点——表行格式变了？")
    return problems


def check(api_dir: Path, pagesets_dir: Path) -> list[str]:
    """返回问题清单（空 = 通过）。每条都写「怎么修」。"""
    problems: list[str] = []
    code, dupes = derive_code(api_dir)
    if not code:
        problems.append(f"{api_dir} 下没派生出任何路由——路径指错了？（零条不是通过）")
        return problems + dupes
    declared, parse_problems = derive_declared(pagesets_dir)
    internal, internal_problems = _derive_declared_from_files(
        list(INTERNAL_CONTRACT_FILES))
    for key, value in internal.items():      # 内部面与页集面同一张「已声明」表
        declared.setdefault(key, value)
    parse_problems.extend(internal_problems)
    storefront, storefront_problems = _derive_declared_from_files([STOREFRONT_CONTRACT])
    for key, value in storefront.items():    # 店面单独一份文件，同样进「已声明」表
        declared.setdefault(key, value)
    parse_problems.extend(storefront_problems)
    trade, trade_problems = _derive_declared_from_files([TRADE_CONTRACT])
    for key, value in trade.items():
        declared.setdefault(key, value)
    parse_problems.extend(trade_problems)
    parse_problems.extend(check_storefront_identity(STOREFRONT_CONTRACT[0]))
    problems.extend(parse_problems)
    problems.extend(dupes)

    allow = {(e["method"], norm(e["path"])): e for e in INFRA_ENDPOINTS}

    # 1) 实现有、声明无（且不在基础设施白名单里）
    for key, (raw, src) in sorted(code.items()):
        if key in declared or key in allow:
            continue
        problems.append(
            f"[未声明] {key[0]} {norm(raw)}（{src}）——"
            f"在对应页面集的 api-contract.md 补一行（含权限列），"
            f"或确认它是基础设施端点后登记到本闸 INFRA_ENDPOINTS 并写明声明出处")

    # 2) 声明有、实现无
    for key, (raw, pack) in sorted(declared.items()):
        if key in code:
            continue
        problems.append(
            f"[悬空声明] {key[0]} {norm(raw)}（{pack}/api-contract.md）——"
            f"实现它（无车道就如实 501 + planned_lane），或从契约里删掉这行")

    # 3) 白名单过期（免检牌必须跟着路由走）
    for key, entry in sorted(allow.items()):
        if key in code:
            continue
        problems.append(
            f"[白名单过期] {key[0]} {key[1]}（{entry['declared_at']}）——"
            f"该路由已不存在，从 INFRA_ENDPOINTS 撤掉这条")

    # 4) 白名单与契约重复声明（两边都有：说明它其实是业务面，不该挂免检牌）
    for key in sorted(allow):
        if key in declared:
            problems.append(
                f"[白名单冗余] {key[0]} {key[1]} 已被 {declared[key][1]} 契约声明——"
                f"它是业务面，从 INFRA_ENDPOINTS 撤掉")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="REST 实现面 ↔ 声明契约双向对拍")
    ap.add_argument("--api-dir", default=str(DEFAULT_API_DIR),
                    help="fd_erp_vertical_api 包目录（默认按工作区布局推）")
    ap.add_argument("--pagesets-dir", default=str(DEFAULT_PAGESETS_DIR),
                    help="templates/supply-chain/pagesets 目录（默认按工作区布局推）")
    args = ap.parse_args(argv)

    api_dir = Path(args.api_dir)
    pagesets_dir = Path(args.pagesets_dir)

    # 缺输入 → SKIP（退出 2），不假红也不假绿
    missing = [str(p) for p in (api_dir, pagesets_dir) if not p.is_dir()]
    if missing:
        print(f"SKIP: 兄弟仓不在场，无法对拍（缺 {', '.join(missing)}）")
        return 2

    problems = check(api_dir, pagesets_dir)
    code, _ = derive_code(api_dir)
    declared, _ = derive_declared(pagesets_dir)
    # 内部面契约也进了判定人口（check() 里与页集契约合表比对），所以汇总行必须把它
    # 算进去：只印页集数会让「验了多少条」比「比了多少条」少一截——读的人以为内部面
    # 没被对拍过，或者以为数字变小是端点丢了。两处口径同源（同一个 derive 函数）。
    internal, _ = _derive_declared_from_files(list(INTERNAL_CONTRACT_FILES))
    storefront, _ = _derive_declared_from_files([STOREFRONT_CONTRACT])
    trade, _ = _derive_declared_from_files([TRADE_CONTRACT])
    if problems:
        print(f"FAIL: REST 面与声明契约不一致（{len(problems)} 处）：")
        for p in problems:
            print("  " + p)
        return 1
    print(f"OK: {len(code)} 条实现端点与 "
          f"{len(declared) + len(internal) + len(storefront) + len(trade)}"
          f" 条契约声明双向一致（页集 {len(declared)} + 内部面 {len(internal)}"
          f" + 店面 {len(storefront)} + 协商 {len(trade)}；"
          f"基础设施端点 {len(INFRA_ENDPOINTS)} 条已登记理由）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
