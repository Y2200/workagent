"""
全量测试 runner：以独立子进程逐个运行 scripts/test_*.py

项目测试是脚本式（`python -m work_agent.scripts.test_xxx`），非 pytest。
本脚本负责"一键全量跑 + 汇总报告 + 失败即非零退出"，供 CI（GitHub Actions）
与本地回归使用。每个脚本在独立子进程内运行，隔离各自模块状态；共享数据库则顺序执行。

用法：
    python -m work_agent.scripts.run_all_tests                     # 跑全部
    python -m work_agent.scripts.run_all_tests --only test_parser,test_prompt_manager
    python -m work_agent.scripts.run_all_tests --skip test_milvus,test_production_suite
    python -m work_agent.scripts.run_all_tests --report-dir ci-reports --timeout 1200

行为：
- 自动定位仓库根（本文件位于 src/work_agent/scripts/），以仓库根为工作目录运行，
  使相对路径（knowledge/、.env、prompts/、reports/）始终正确解析。
- 结果汇总为 JSON（<report-dir>/ci_test_results.json），每个脚本的输出写入
  <report-dir>/logs/<name>.log。
- 任一脚本失败/超时 → 退出码 1；--skip 的脚本不算失败。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 仓库根 = src/work_agent/scripts 的上三层（scripts -> work_agent -> src -> 根）
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = Path(__file__).resolve().parent

# 默认跳过集合：预留登记已知与 CI 环境冲突/耗时的脚本（默认全跑，不改动则不设）
DEFAULT_SKIP: set[str] = set()


def discover_test_scripts() -> list[str]:
    """扫描 scripts/ 下所有 test_*.py（排除本脚本），返回模块名（无 .py）。"""
    names = sorted(
        p.stem
        for p in SCRIPTS_DIR.glob("test_*.py")
        if p.stem != "run_all_tests"
    )
    return names


def _subprocess_env() -> dict:
    """继承父进程环境，并强制子进程以 UTF-8 输出（避免 Windows GBK 解码崩溃）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_one(name: str, timeout: int, report_dir: Path) -> dict:
    """在独立子进程运行单个测试模块，返回结果记录。"""
    log_file = report_dir / "logs" / f"{name}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", f"work_agent.scripts.{name}"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
            timeout=timeout,
        )
        output = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
        with log_file.open("w", encoding="utf-8") as f:
            f.write(output)
        ok = proc.returncode == 0
        status = "ok" if ok else "failed"
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (f"\n[Timeout {timeout}s] 进程被终止。\n")
        with log_file.open("w", encoding="utf-8") as f:
            f.write(output)
        ok = False
        status = "timeout"
    duration = round(time.time() - start, 2)

    return {
        "name": name,
        "status": status,
        "ok": ok,
        "duration_sec": duration,
        "log": str(log_file),
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台/管道默认 GBK，重配置为 UTF-8 避免打印中文乱码
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Work Agent 全量测试 runner")
    parser.add_argument("--only", help="仅运行指定脚本，逗号分隔（例：test_parser,test_milvus）")
    parser.add_argument("--skip", help="跳过指定脚本，逗号分隔")
    parser.add_argument("--report-dir", default="reports", help="报告输出目录（默认 reports）")
    parser.add_argument("--timeout", type=int, default=1200, help="单脚本超时秒数（默认 1200）")
    args = parser.parse_args(argv)

    names = discover_test_scripts()

    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}
        names = [n for n in names if n in only]
    if args.skip:
        skip = {s.strip() for s in args.skip.split(",") if s.strip()}
        names = [n for n in names if n not in skip]

    names = [n for n in names if n not in DEFAULT_SKIP]
    if not names:
        print("没有可运行的测试脚本。")
        return 1

    report_dir = Path(args.report_dir)
    if not report_dir.is_absolute():
        report_dir = REPO_ROOT / report_dir

    print(f"仓库根: {REPO_ROOT}")
    print(f"共 {len(names)} 个测试脚本，逐个运行（每脚本超时 {args.timeout}s）...\n")

    results: list[dict] = []
    failed_names: list[str] = []
    for idx, name in enumerate(names, 1):
        result = run_one(name, args.timeout, report_dir)
        results.append(result)
        if not result["ok"]:
            failed_names.append(name)
        print(
            f"[{idx}/{len(names)}] {name:<34} {result['status']:<8} "
            f"{result['duration_sec']:>7.2f}s"
        )

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_root": str(REPO_ROOT),
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "failed_names": failed_names,
        "results": results,
    }
    report_file = report_dir / "ci_test_results.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print(
        f"汇总: {summary['ok']}/{summary['total']} 通过, "
        f"{summary['failed']} 失败, 报告: {report_file}"
    )
    if failed_names:
        print("失败列表: " + ", ".join(failed_names))
        for name in failed_names:
            log = next(r["log"] for r in results if r["name"] == name)
            print(f"  - {name} 日志: {log}")
        print("\n查看单个失败详情: cat <上述日志路径>")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
