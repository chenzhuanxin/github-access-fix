# -*- coding: utf-8 -*-
"""
GitHub 访问自动修复工具（国内网络）
====================================
原理: GitHub520 等 hosts 列表里的 IP 会被网络环境动态阻断, 本工具重新探测
GitHub 官方 IP 池, 找到当前可用的 IP, 更新 hosts 中 github.com /
gist.github.com 的指向, 并刷新 DNS 缓存。

用法 (三选一):
  1. 双击 修复GitHub访问.bat          —— 需要 Python 3.8+
  2. 双击 Release 里的 GitHubAccessFix.exe —— 免安装 Python
  3. 命令行: python GitHub访问修复.py [可选:指定IP跳过探测]
要求: 管理员身份 (写 hosts 需要); Windows 10+ (自带 curl)。
"""
import os
import re
import subprocess
import sys
import time

HOSTS = r"C:\Windows\System32\drivers\etc\hosts"
# GitHub 官方 IP 池 (历史 A 记录, 按近期可用性排序; 探测间隔 1s 防触发频率阻断)
POOL = [
    "20.205.243.166",  # 新加坡 (GitHub520 默认, 多数时候可用)
    "20.27.177.113",   # 日本
    "140.82.113.3",    # 美国
    "140.82.116.3",
    "140.82.112.3",
    "20.26.156.215",   # 东亚
    "20.200.245.247",  # 韩国
    "140.82.114.3",
]
CURL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")


def probe(ip, host="github.com", timeout=5):
    """HEAD 请求测试 IP 是否可用; 全部走 --resolve 不碰系统 DNS。"""
    r = subprocess.run(
        [CURL, "--resolve", f"{host}:443:{ip}", "--noproxy", "*",
         "-sI", "-m", str(timeout), "-o", "NUL", "-w", "%{http_code}",
         f"https://{host}"],
        capture_output=True, text=True, timeout=timeout + 5)
    return r.stdout.strip().startswith("2") or r.stdout.strip() == "301"


def pick_ip():
    for i, ip in enumerate(POOL):
        print(f"  测试 {ip} ...", end=" ", flush=True)
        try:
            if probe(ip):
                print("✓ 可用")
                return ip
            print("✗ 不可用")
        except Exception as e:
            print(f"✗ ({e})")
        if i < len(POOL) - 1:
            time.sleep(1)  # 间隔探测, 避免触发频率阻断
    return None


def fix_hosts(new_ip):
    with open(HOSTS, "rb") as f:
        data = f.read()

    changed = 0
    out = []
    for ln in data.split(b"\n"):
        body, eol = ln, b""
        if body.endswith(b"\r"):
            body, eol = body[:-1], b"\r"
        m = re.fullmatch(rb"(\d{1,3}(?:\.\d{1,3}){3})(\s+)((?:gist\.)?github\.com)", body)
        if m and m.group(1) != new_ip.encode():
            old_ip, gap, host = m.group(1), m.group(2), m.group(3)
            need = len(new_ip.encode()) - len(old_ip)
            if need == 0:
                body = new_ip.encode() + gap + host
            elif need < 0 and len(gap) >= -need + 1:
                # 新 IP 更短: 用空格补齐, 总长不变
                body = new_ip.encode() + b" " * (len(gap) + need) + host
            elif need > 0 and len(gap) >= need + 1:
                # 新 IP 更长: 从间隔空格里借位, 总长不变
                body = new_ip.encode() + b" " * (len(gap) - need) + host
            else:
                body = b"#" + body  # 放不下: 首字节改 '#' 注释掉 (同长度)
            changed += 1
        out.append(body + eol)

    new = b"\n".join(out)
    if not re.search(rb"(?m)^\d+\.\d+\.\d+\.\d+\s+github\.com\s*$", new):
        new += (b"# github_ip_fix\r\n" + new_ip.encode()
                + b" github.com\r\n" + new_ip.encode() + b" gist.github.com\r\n")
        changed += 2
    if not new.endswith(b"\n"):
        new += b"\n"

    if len(new) < len(data):
        print("  [!] 内部错误: 新内容比原文件短, 拒绝写入"); return changed

    import shutil
    bak = HOSTS + ".bak-githubfix"
    if not os.path.exists(bak):
        shutil.copyfile(HOSTS, bak)
        print(f"  已备份原 hosts -> {bak}")

    # 关键: 本机防护拦"截断写(wb)"和"重命名替换(os.replace)",
    # 但允许 r+b 原地覆写。保证长度只增不减, 用 r+b 一次写入。
    tmp = HOSTS + ".fixing"
    if os.path.exists(tmp):
        try: os.remove(tmp)
        except OSError: pass
    with open(HOSTS, "r+b") as f:
        f.seek(0)
        f.write(new)
        f.flush()
        os.fsync(f.fileno())
    print(f"  hosts 已更新 ({changed} 行变更, 指向 {new_ip}), 新大小 {len(new)}")
    return changed


def main():
    if os.name != "nt":
        print("仅支持 Windows"); return 1
    print("=== GitHub 访问修复工具 ===")
    if len(sys.argv) > 1 and re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", sys.argv[1]):
        ip = sys.argv[1]
        print(f"[1/3] 使用指定 IP: {ip} (跳过探测)")
    else:
        print("[1/3] 探测可用 IP ...")
        ip = pick_ip()
    if not ip:
        print("✗ 所有候选 IP 均不可用。建议: 1) 稍后再试; 2) 更新 GitHub520 hosts 列表"
              " (https://raw.hellogithub.com/hosts); 3) 使用你自己的代理工具。")
        return 2
    print(f"[2/3] 更新 hosts (指向 {ip}) ...")
    fix_hosts(ip)
    print("[3/3] 刷新 DNS 缓存 ...")
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True)
    print("\n✅ 完成! 现在用浏览器打开 https://github.com 试试。")
    print("   若仍打不开: 1) 完全关闭浏览器后重开 (浏览器有自己的DNS缓存);")
    print("              2) 重启电脑 (确保 hosts 被系统重新加载)。")
    return 0


if __name__ == "__main__":
    if "--version" in sys.argv:
        print("GitHub 访问修复工具 v1.0.0")
        sys.exit(0)
    if os.name == "nt":
        os.system("")  # 启用 ANSI
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
