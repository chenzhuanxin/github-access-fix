# -*- coding: utf-8 -*-
"""
GitHub 访问自动修复工具 v2.0（国内网络）
========================================
功能:
  1. 自动获取 GitHub520 列表并定期更新 (双镜像: hellogithub 官方 + jsDelivr CDN,
     本地缓存 24 小时, 失败自动回退旧缓存)
  2. 多源合并候选 IP: GitHub520 + DoH 实时解析(阿里/360) + 内置历史池
  3. SNI 探测(1 秒间隔防频率阻断)选最快可用 IP, 更新 hosts 的
     github.com / gist.github.com, 并整体刷新 GitHub520 区块
  4. 可选: 安装 Windows 计划任务, 每天自动探测更新 (--install-task)

用法:
  双击 修复GitHub访问.bat          (需要 Python 3.8+)
  双击 Release 里的 GitHubAccessFix.exe (免装 Python)
  命令行:
    python GitHub访问修复.py                 # 全流程: 更新列表+探测+修复
    python GitHub访问修复.py 20.205.243.166  # 指定 IP, 跳过探测
    python GitHub访问修复.py --install-task  # 安装每日自动更新计划任务
    python GitHub访问修复.py --uninstall-task
    python GitHub访问修复.py --version
要求: 管理员身份 (写 hosts); Windows 10+ (自带 curl)。
"""
import json
import os
import re
import subprocess
import sys
import time

__version__ = "2.0.0"

HOSTS = r"C:\Windows\System32\drivers\etc\hosts"
CURL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
TASK_NAME = "GitHubIPFix"

# ---------- IP 候选源 ----------
G520_SOURCES = [                      # GitHub520 列表镜像 (按优先级)
    "https://raw.hellogithub.com/hosts",
    "https://cdn.jsdelivr.net/gh/521xueweihan/GitHub520@main/hosts",
]
DOH_ENDPOINTS = [                     # DoH 实时解析 (返回官方最新 A 记录)
    "https://dns.alidns.com/resolve?name=github.com&type=A",
    "https://doh.360.cn/resolve?name=github.com&type=A",
]
BUILTIN_POOL = [                      # 官方历史解析 IP 池
    "20.205.243.166",  # 新加坡
    "20.27.177.113",   # 日本
    "140.82.113.3",
    "140.82.116.3",
    "140.82.112.3",
    "20.26.156.215",
    "20.200.245.247",  # 韩国
    "140.82.114.3",
]
CACHE_TTL = 24 * 3600                 # GitHub520 列表缓存 24 小时
MAX_PROBE = 10                        # 单次最多探测 10 个候选
PROBE_GAP = 1.0                       # 探测间隔(秒), 防频率阻断

CACHE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                         "GitHubIPFix")
CACHE_FILE = os.path.join(CACHE_DIR, "github520_cache.txt")


def log(msg):
    print(msg, flush=True)


# ============================================================
#  来源 1: GitHub520 列表 (自动获取 + 定期更新 + 缓存回退)
# ============================================================
def fetch_github520(force=False):
    """返回列表文本; 优先缓存(24h 内), 过期或强制时联网更新, 全失败回退旧缓存"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cached, cached_age = None, None
    if os.path.exists(CACHE_FILE):
        cached = open(CACHE_FILE, "r", encoding="utf-8", errors="ignore").read()
        cached_age = time.time() - os.path.getmtime(CACHE_FILE)

    if cached and not force and cached_age < CACHE_TTL:
        log(f"  GitHub520 列表: 使用本地缓存 ({cached_age/3600:.1f} 小时前更新, "
            f"{CACHE_TTL//3600} 小时后自动刷新)")
        return cached

    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for i, url in enumerate(G520_SOURCES):
        try:
            log(f"  GitHub520 列表: 从镜像{i+1}获取 {url} ...", )
            with urllib_request.urlopen(
                    urllib_request.Request(url, headers=ua), timeout=10) as r:
                text = r.read().decode("utf-8", "ignore")
            if "github.com" in text and re.search(r"^\d+\.\d+\.\d+\.\d+\s+", text, re.M):
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    f.write(text)
                log(f"    ✓ 获取成功并已缓存 ({len(text)} 字节, 24 小时内不再重复下载)")
                return text
            log("    ✗ 内容异常, 换下一个镜像")
        except Exception as e:
            log(f"    ✗ 失败 ({str(e)[:60]})")

    if cached:
        log(f"  ⚠ 所有镜像失败, 回退本地缓存 ({cached_age/3600:.1f} 小时前)")
        return cached
    log("  ⚠ GitHub520 列表不可用, 仅使用 DoH 解析 + 内置池")
    return None


# ============================================================
#  来源 2: DoH 实时解析 (阿里 / 360, 返回官方最新 A 记录)
# ============================================================
def fetch_doh_ips():
    ips = []
    for url in DOH_ENDPOINTS:
        m = re.search(r"//([^/]+)/", url)
        name = m.group(1) if m else url
        try:
            with urllib_request.urlopen(
                    urllib_request.Request(url, headers={"Accept": "application/dns-json"}),
                    timeout=8) as r:
                data = json.loads(r.read().decode("utf-8", "ignore"))
            got = [a["data"] for a in data.get("Answer", [])
                   if a.get("type") == 1 and re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", a.get("data", ""))]
            log(f"  DoH 实时解析 [{name}]: {got or '无记录'}")
            ips.extend(got)
        except Exception as e:
            log(f"  DoH 实时解析 [{name}]: 失败 ({str(e)[:50]})")
    return ips


def github520_target_ips(text):
    """从 GitHub520 列表内容中提取 github.com / gist.github.com 的 IP"""
    ips = []
    for m in re.finditer(r"(?m)^(\d{1,3}(?:\.\d{1,3}){3})\s+(?:gist\.)?github\.com\s*$", text):
        if m.group(1) not in ips:
            ips.append(m.group(1))
    return ips


# ============================================================
#  探测: SNI=github.com 的 TLS 实测 (间隔 1 秒防频率阻断)
# ============================================================
def probe(ip, timeout=5):
    r = subprocess.run(
        [CURL, "--resolve", f"github.com:443:{ip}", "--noproxy", "*",
         "-sI", "-m", str(timeout), "-o", "NUL",
         "-w", "%{http_code} %{time_total}", "https://github.com"],
        capture_output=True, text=True, timeout=timeout + 5)
    parts = r.stdout.strip().split()
    if parts and parts[0].startswith("2"):
        return float(parts[1])
    return None


def pick_best(candidates):
    uniq = []
    for ip in candidates:
        if ip and ip not in uniq:
            uniq.append(ip)
    uniq = uniq[:MAX_PROBE]
    log(f"  共 {len(uniq)} 个候选, 逐个实测 (间隔 {PROBE_GAP:.0f} 秒) ...")
    best, best_t = None, 1e9
    for i, ip in enumerate(uniq):
        log(f"  测试 {ip} ...", end=" ", flush=True)
        try:
            t = probe(ip)
        except Exception:
            t = None
        if t is None:
            log("✗")
        else:
            log(f"✓ {t:.2f}s")
            if t < best_t:
                best, best_t = ip, t
        if i < len(uniq) - 1:
            time.sleep(PROBE_GAP)
    return best


# ============================================================
#  hosts 写入: r+b 原地覆写 (长度只增不减), 绕开截断/重命名拦截
# ============================================================
def refresh_g520_block(data, fetched):
    """用新获取的 GitHub520 列表整体替换 hosts 中的 GitHub520 区块;
    新内容较短时用注释行补齐, 保证总长不减 (r+b 覆写的前提)"""
    marker = b"# GitHub520 Host Start"
    if not fetched or marker not in data:
        return data, False
    pre = data.split(marker, 1)[0]
    fb = fetched.encode("utf-8", "ignore")
    if not fb.endswith(b"\n"):
        fb += b"\n"
    new = pre + fb
    if len(new) < len(data):  # 补齐注释, 保证长度不减
        pad = len(data) - len(new)
        new += b"# " + b"-" * max(pad - 2, 1) + b"\n"
    return new, True


def set_github_ip(data, new_ip):
    """把所有 github.com / gist.github.com 行指向 new_ip (同长度技巧)"""
    nb = new_ip.encode()
    out, changed = [], 0
    for ln in data.split(b"\n"):
        body, eol = ln, b""
        if body.endswith(b"\r"):
            body, eol = body[:-1], b"\r"
        m = re.fullmatch(rb"(\d{1,3}(?:\.\d{1,3}){3})(\s+)((?:gist\.)?github\.com)", body)
        if m and m.group(1) != nb:
            old_ip, gap, host = m.group(1), m.group(2), m.group(3)
            need = len(nb) - len(old_ip)
            if need == 0:
                body = nb + gap + host
            elif need < 0 and len(gap) >= -need + 1:
                body = nb + b" " * (len(gap) + need) + host
            elif need > 0 and len(gap) >= need + 1:
                body = nb + b" " * (len(gap) - need) + host
            else:
                body = b"#" + body
            changed += 1
        out.append(body + eol)
    new = b"\n".join(out)
    if not new.endswith(b"\n"):
        new += b"\n"
    if not re.search(rb"(?m)^\d+\.\d+\.\d+\.\d+\s+github\.com\s*$", new):
        new += (b"# github_ip_fix\r\n" + nb + b" github.com\r\n"
                + nb + b" gist.github.com\r\n")
        changed += 2
    return new, changed


def backup_hosts():
    """修改前备份原 hosts (新建普通文件, 不受 hosts 自身写保护影响)"""
    try:
        with open(HOSTS, "rb") as f:
            data = f.read()
        bak = HOSTS + ".bak-githubfix"
        with open(bak, "wb") as f:
            f.write(data)
        return bak
    except Exception:
        return None


def write_hosts(new):
    with open(HOSTS, "rb") as f:
        old_len = len(f.read())
    if len(new) < old_len:
        new += b"# " + b"-" * max(old_len - len(new) - 2, 1) + b"\n"
    with open(HOSTS, "r+b") as f:
        f.seek(0)
        f.write(new)
        f.flush()
        os.fsync(f.fileno())
    return len(new)


# ============================================================
#  计划任务: 每天自动探测更新 (真正意义的定期更新)
# ============================================================
def install_task():
    if getattr(sys, "frozen", False):
        tr = f'"{sys.executable}"'
    else:
        tr = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
    r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/TR", tr,
                        "/SC", "DAILY", "/ST", "09:00", "/RL", "HIGHEST", "/F"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        log(f"✅ 计划任务已安装: 每天 09:00 自动探测并更新 (任务名 {TASK_NAME})")
        log("   删除方法: python GitHub访问修复.py --uninstall-task")
    else:
        log(f"✗ 安装失败: {(r.stderr or r.stdout).strip()[:120]}")
        log("   请以管理员身份运行; 或到'任务计划程序'手动创建。")


def uninstall_task():
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                       capture_output=True, text=True)
    log("✅ 计划任务已删除" if r.returncode == 0
        else f"✗ 删除失败: {(r.stderr or r.stdout).strip()[:120]}")


# ============================================================
#  主流程
# ============================================================
def main():
    if os.name != "nt":
        print("仅支持 Windows"); return 1
    if "--version" in sys.argv:
        print(f"GitHub 访问修复工具 v{__version__}"); return 0
    if "--install-task" in sys.argv:
        install_task(); return 0
    if "--uninstall-task" in sys.argv:
        uninstall_task(); return 0

    print(f"=== GitHub 访问修复工具 v{__version__} ===")

    # [1] 多源收集候选 IP
    print("[1/4] 获取候选 IP ...")
    g520 = fetch_github520(force="--refresh" in sys.argv)
    candidates = []
    candidates += fetch_doh_ips()
    candidates += github520_target_ips(g520 or "")
    candidates += BUILTIN_POOL

    # [2] 探测选最快 (指定 IP 则跳过)
    print("[2/4] 探测最快可用 IP ...")
    if len(sys.argv) > 1 and re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", sys.argv[1]):
        best = sys.argv[1]
        log(f"  使用指定 IP: {best} (跳过探测)")
    else:
        if "--no-probe" in sys.argv:
            best = candidates[0] if candidates else None
            log(f"  跳过探测, 使用首个候选: {best}")
        else:
            best = pick_best(candidates)
    if not best:
        print("✗ 所有候选 IP 均不可用。建议: 稍后再试 / 更新本工具 / 使用代理。")
        return 2
    log(f"  选定: {best}")

    # [3] 更新 hosts: 整体刷新 GitHub520 区块 + github.com/gist 指向最佳 IP
    print("[3/4] 更新 hosts ...")
    with open(HOSTS, "rb") as f:
        data = f.read()
    bak = backup_hosts()
    if bak:
        log(f"  已备份原 hosts -> {bak}")
    new, refreshed = refresh_g520_block(data, g520)
    new, changed = set_github_ip(new, best)
    size = write_hosts(new)
    log(f"  GitHub520 区块{'已整体刷新' if refreshed else '未找到(跳过)'}; "
        f"github.com/gist 指向 {best} ({changed} 行变更), 文件 {size} 字节")

    # [4] 刷新 DNS 缓存
    print("[4/4] 刷新 DNS 缓存 ...")
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True)

    print(f"\n✅ 完成! 刷新浏览器访问 https://github.com 试试。")
    print("   个别页面仍异常: 关闭浏览器重开 / 重启电脑 (hosts 已是正确内容)。")
    print("   想每天自动更新: python GitHub访问修复.py --install-task")
    return 0


import urllib.request as urllib_request  # noqa: E402 (置于顶部亦可)

if __name__ == "__main__":
    if os.name == "nt":
        os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
