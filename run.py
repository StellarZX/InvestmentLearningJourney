# -*- coding: utf-8 -*-
"""
投资系统统一入口（run.py）
==========================
根目录入口，通过参数调用 Code/ 下的各功能脚本：

  python run.py --index      指数报告（启动指数看板，http://127.0.0.1:8050）
  python run.py --sector     行业报告（生成 03_SectorReport/sector_report.html）
  python run.py --portfolio  流水记录（启动持仓管理，http://127.0.0.1:8051）
  python run.py --all        全部功能

可组合：python run.py --sector --portfolio
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.join(BASE, 'Code')
PY = sys.executable


def _run(script, *args):
    p = os.path.join(CODE, script)
    if not os.path.exists(p):
        print(f'[err] 未找到 {p}')
        return
    print(f'>>> 运行 {script} {" ".join(args)}')
    subprocess.run([PY, p, *args])


def main():
    args = sys.argv[1:]
    if not args or '--all' in args or '-a' in args:
        print(__doc__)
        return
    if '--index' in args or '-i' in args:
        _run('index_dashboard.py')
    if '--sector' in args or '-s' in args:
        _run('sector_report.py')
    if '--portfolio' in args or '-p' in args:
        _run('portfolio_app.py')


if __name__ == '__main__':
    main()
