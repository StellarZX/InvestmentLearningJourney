# -*- coding: utf-8 -*-
"""
投资系统统一入口（run.py）
==========================
根目录入口，通过参数调用 Code/ 下的各功能脚本：

  python run.py --index      持仓基金分析报告（生成 PortfolioReport/YYYYMMDD.html）
  python run.py --plate      板块分析报告（生成 PlateReport/YYYYMMDD.html，东财官方行业+概念）
  python run.py --sector     兼容旧参数：同 --plate（行业报告已由板块报告取代）
  python run.py --portfolio  流水记录（启动持仓管理，http://127.0.0.1:8051）
  python run.py --export     更新根 README 第 4 节「组合持仓」表
  python run.py --all        全部功能

可组合：python run.py --plate --portfolio
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
    # 通用透传参数（--no-refresh / --only-concept 等传给子脚本）
    extra = [a for a in args if a.startswith('--') and a not in
             ('--index', '-i', '--plate', '--sector', '-s', '--portfolio', '-p',
              '--export', '-e', '--all', '-a')]
    if '--index' in args or '-i' in args:
        _run('portfolio_report.py', *extra)
    if '--plate' in args:
        _run('plate_report.py', *extra)
    if '--sector' in args or '-s' in args:
        print('提示: --sector 行业报告已由 --plate 板块分析报告取代，本次运行板块报告')
        _run('plate_report.py', *extra)
    if '--portfolio' in args or '-p' in args:
        _run('portfolio_app.py')
    if '--export' in args or '-e' in args:
        _run('export_positions.py', '--write')


if __name__ == '__main__':
    main()
