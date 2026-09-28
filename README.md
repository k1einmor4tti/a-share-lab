# A Share Lab

本机单用户 A 股日线研究与量化回测平台。使用 [AKQuant](https://github.com/akfamily/akquant) 运行策略，东方财富提供主要行情，BaoStock 补充可获得的沪深行情与退市目录。项目需求、设计与逐项进度见 [OpenSpec](openspec/changes/a-share-local-platform/)。

## 启动

需要 Python 3.12、Git，以及首次下载行情时的网络连接。所有服务只绑定本机。

```bash
cd ~/github.com/a-share-lab
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/uvicorn app.server:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/>。接口文档位于 <http://127.0.0.1:8000/api/docs>。首次启动会自动加载目录并在后台下载全市场历史日线；页面可以立即使用。下载几千只股票可能耗时数小时，关闭服务后重新启动会根据已验证的日期区间继续处理。数据存放在仓库的 `data/` 目录，已被 Git 忽略。可以用 `ASHARE_DATA_DIR` 指定其他数据目录。

## 使用

1. **市场总览**：查看上证指数、深证成指、创业板指、沪深 300、中证 500 最近已完成收盘的日线，搜索股票代码或名称，检查价格历史、原始价/前复权价与数据来源。支持沪深京 A 股以及目录中可识别的退市股。
2. **更新全市场数据**：点击按钮启动后台任务。已有日期通过已验证区间跳过，缺失日期及失败区间会重试；前复权锚点变化时，只有新数据覆盖全部旧交易日才替换旧序列。收盘前点过按钮，收盘后可以再点一次。失败代码与原因在市场页展示；选中股票可以加入优先队列。
3. **策略回测**：选择买入持有、均线交叉、海龟突破、RSI 反转或布林带模块，填写六位代码和参数。回测使用本地已验证的日线；历史尚未下载时先点“优先下载此股”。报告含收益、同期沪深 300、资金曲线、订单与假设，可在本机保存、对比及下载 ZIP。策略信号在收盘后产生，按下一交易日开盘成交，采用 T+1、100 股提交整手及可调费用。分红送转使用前复权价格代理估值，因此绝对成交价、股数与最低佣金仍是近似；停牌、涨跌停的处理范围见每份报告。
4. **策略助手**：选取含 `SKILL.md` 的本地文件夹，或粘贴公开 GitHub 仓库/`tree/<branch>/<dir>` 链接。平台只保存 Markdown/TXT，不运行其中的脚本；一次最多导入 20 个 skill、128 个文件、1 MB 文本。勾选最多五个 skill 后可向本机 DSH 问答、索取参数建议。

## DSH 安全边界

助手使用 `ASHARE_DSH_URL` 指定的本机 DSH，默认 `http://127.0.0.1:3080`。平台会安装并逐字校验 [`config/dsh-readonly/agent.cordis.yml`](config/dsh-readonly/agent.cordis.yml)，再用一个不含 skill 内容的探测问题读取**实际模型请求**的工具清单。只有工具清单为空时才会发送导入资料。DSH 离线、预设被修改、无法检查清单或全局插件仍注入工具时，助手会关闭并显示原因；行情和回测照常工作。当前这台电脑的 DSH 全局插件会注入浏览器和 SSH 工具，因此助手按设计保持关闭。服务端没有自动修改这些全局插件。

## 数据与覆盖限制

- 数据库为 `data/market.sqlite3`，各股票和指数的日线为 `data/bars/` 下的 Parquet，回测快照为 `data/results/`，导入的 skill 文本为 `data/skills/`。这些本机数据都不推送到 GitHub。
- 东方财富请求失败时，沪深股票及指数可改用 BaoStock；北交所股票目前只依赖东方财富。平台显示每只股票的实际日期、来源、失败状态，不承诺所有已退市股票都能获得完整 20 年历史，也不把当前目录当作任意历史日的完整上市名单。
- 本项目仅用于研究，不含券商交易、实盘指令、分钟线或多用户访问。

## 开发检查

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest -q
openspec validate a-share-local-platform --strict
```

OpenSpec CLI 仅用于维护规格；运行平台不需要它。`main` 按 OpenSpec 任务阶段性提交，阶段完成后由独立子 agent 审查，修复另行提交。
