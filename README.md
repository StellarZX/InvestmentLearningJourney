# 投资方法与记录

个人投资方法、执行记录与复盘（数据仅供参考，不构成投资建议）。

- **本地使用**：`update_portfolio.sh` 记录持仓流水，`daily_report.sh` 生成持仓基金分析和板块分析报告并刷新导航页。

## Linux / Miniconda 使用

项目默认使用 Miniconda 环境 `Inves`。先在该环境安装依赖：

```bash
conda activate Inves
python -m pip install -r requirements.txt
```

启动持仓流水网页：

```bash
./update_portfolio.sh
```

脚本会监听 `0.0.0.0:8051`，服务器本机可访问 `http://127.0.0.1:8051`，同一局域网其他电脑访问 `http://服务器局域网IP:8051`。如环境名称不同，可设置 `INVEST_ENV=环境名`；如需更换端口，设置 `PORTFOLIO_PORT`。

前台启动时，保持当前终端打开；按 `Ctrl+C` 即可关闭网页服务。推荐服务器长期运行时放到后台：

```bash
mkdir -p logs
nohup ./update_portfolio.sh > logs/portfolio_app.log 2>&1 &
echo $! > logs/portfolio_app.pid
```

后台服务关闭方式：

```bash
kill "$(cat logs/portfolio_app.pid)"
rm -f logs/portfolio_app.pid
```

如果 PID 文件不存在，可先查找进程：

```bash
pgrep -af 'Code/portfolio_app.py'
kill <进程号>
```

确认网页是否运行：

```bash
curl http://127.0.0.1:8051/api/summary
```

每个工作日（周一至周五）西班牙时间 18:00 自动生成两份报告并刷新首页，周末不运行（首次只需执行一次）：

```bash
./install_daily_report_cron.sh
```

也可以手动执行 `./daily_report.sh`。报告运行日志写入 `logs/daily_report.log`。

查看或删除每日定时任务：

```bash
crontab -l
crontab -e
```

删除包含 `InvestmentLearningJourney daily report` 的那一行即可；这不会关闭流水网页服务。

`daily_report.sh` 会在报告有变化时自动执行 `git add`、提交并推送到 GitHub；请先确认服务器已配置好 Git 用户信息、远程仓库和免交互认证（SSH key 或 credential helper）。

`update_portfolio.sh` 是持续运行的网页服务；每日报告定时任务与它相互独立。网页服务没有登录认证，不建议直接暴露到公网。
