# RAG 评测说明

## 当前入口与评测范围

本目录区分“检索排名”和“最终问答”两种评测，不能把检索命中当作回答正确率。
演示文档均为虚构制度，不代表真实公司规定。

- `run_retrieval_eval.py`：直接读取现有知识库索引，只做本地问题向量化与检索，不调用聊天模型、不写问答历史、不重建索引。
- `retrieval_cases_v1.json`：12 道基础检索题。
- `retrieval_cases_followup_v1.json`：12 道补充检索题，增加口语改写、未测细节和相似制度混淆问题。
- `fixtures/multi_doc_v1/`：上述两批题使用的 6 份 Markdown 文档。
- `run_current_eval.py`：通过当前登录和知识库问答接口运行 `cases.json` 中的 10 道问题，会调用聊天模型并写入历史。
- `run_eval.py`：旧共享接口脚本，仅作为历史记录保留，当前版本不要运行。

报告保存在项目根目录的 `outputs/rag_eval/`，默认不提交 Git。
题集、模拟文档和运行脚本提交 Git，便于核对与复现。

## 只检索评测：准备工作

1. 使用项目 README 的 Docker 步骤配置并启动服务，页面为 <http://127.0.0.1:8003/>。
2. 登录，创建专用评测知识库，仅上传 `fixtures/multi_doc_v1/` 中的 6 份文档并建立索引。
3. 不要把题集 JSON 上传到知识库，以免标准答案泄漏到检索内容。
4. 两份题集记录本次环境的知识库 ID 为 `5`，名称为 `RAG评测_多文档_v1`。其他环境需按实际 ID、名称修改两份题集，运行命令输入该知识库所属用户名。
5. 模型必须已缓存；以下命令使用离线模式，不自动下载模型。

两轮比较期间保持文档、索引、向量模型和 Top-K 不变。
评测会暂时停止 RAG 服务；确保没有其他进程共用当前向量目录。

## 只检索评测：运行命令

以下 PowerShell 命令均在项目根目录执行。
使用现有 Docker 镜像，额外挂载题集和报告目录，不需要为了评测重新构建镜像。

先停止后端并填写知识库所属用户名：

```powershell
docker compose stop backend
$evalOwner = Read-Host "请输入评测知识库所属用户名"
```

基础题集：

```powershell
docker compose run --rm --no-deps -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --volume "${PWD}/evals:/evals:ro" --volume "${PWD}/outputs/rag_eval:/reports" backend python -B /evals/run_retrieval_eval.py --username "$evalOwner" --dataset /evals/retrieval_cases_v1.json
```

补充题集：

```powershell
docker compose run --rm --no-deps -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --volume "${PWD}/evals:/evals:ro" --volume "${PWD}/outputs/rag_eval:/reports" backend python -B /evals/run_retrieval_eval.py --username "$evalOwner" --dataset /evals/retrieval_cases_followup_v1.json
```

无论成功还是报错，完成后恢复服务：

```powershell
docker compose up -d --no-build backend
```

报错时先检查日志，不要通过清空数据或重建索引来绕过问题。
脚本使用本地数据库读取权限核对知识库所属用户，不是 HTTP 登录或用户隔离安全测试。

## 指标与计时口径

每题以“来源文件名一致，且同一个完整片段包含全部预期证据”为相关性标准，匹配时忽略空白字符。
这是一种针对当前固定短文档的规则判分，不是通用语义判分；跨片段证据需另行设计评测。

- Hit@1：正确证据排在第一位的题目比例。
- Hit@4：前四个片段中至少存在一个完整正确证据片段的题目比例。
- MRR@4：正确证据首次出现排名的倒数均值；前四条未命中记为 0。
- `median_seconds` / `max_seconds`：预热后、模型复用条件下，本地问题向量化加 Chroma 查询的耗时中位数和最大值。

计时不包含模型加载、HTTP 请求、聊天生成和历史保存；`model_load_seconds` 和 `warmup_seconds` 单独记录。
当前问答接口的模型实例生命周期与本脚本不同，不能把这些数字当作线上接口或完整回答延迟。
脚本遇到异常会停止；只有完整跑完后才生成汇总报告，未生成报告的失败运行不能当作成功评测。

排名指标可参考 [BEIR 的指标说明](https://github.com/beir-cellar/beir/wiki/Metrics-available)。
本项目使用轻量自定义脚本与模拟数据，未运行 BEIR 官方基准。

## 2026-10-21 检索实测记录

本次使用知识库 5，6 份文档共 6 个片段，模型为 `BAAI/bge-small-zh-v1.5`，设备为 CPU，Top-K 为 4。
两轮报告的索引集合、文档内容和元数据一致。

### 基础题集：12 题

- Hit@1：12/12（100%）。
- Hit@4：12/12（100%）。
- MRR@4：1.0。
- 预热后检索耗时中位数约 45.9 ms，最大约 95.8 ms；模型加载约 8.97 s，另计。
- 题集 SHA-256：`de779c37880363d0573544c9a6995629d7be73cc32c892b8bf6669d9da7bce62`。
- 本地报告：`retrieval_20261021_080330Z_b9c0daec.json`。

### 补充题集：12 题

- Hit@1：11/12（91.7%）。
- Hit@4：12/12（100%）。
- MRR@4：0.9583。
- 预热后检索耗时中位数约 85.6 ms，最大约 132.2 ms；模型加载约 8.21 s，另计。
- 题集 SHA-256：`c123db8cfc8c8bb14cd8a3b9e4bc15ff76e9632b9c7d11bb9673956f0b6a7944`。
- 本地报告：`retrieval_20261021_080942Z_c32c6d0e.json`。

### 排序混淆案例与网页核验

补充题 `f07`：“我还在实习期，出差回来要在几天以内申请报销，最后由谁审核？”

第一条返回 `intern_work.md`，不包含报销期限；第二条返回 `intern_expense.md`，包含完整正确证据。
网页单题验证回答为“出差结束后 7 个自然日内提交，由业务导师审核”，与展示片段中的原文一致。
这证明本次候选中有正确证据且最终回答符合原文，不证明逐句引用绑定，也不代表其余 23 题已做最终回答测试。

### 局限

两批题共 24 道，均为同一组人工构造短文档上的小样本，部分考查相同事实，不是外部独立测试集。
补充题未用于本轮检索调参；若后续针对这些题调参，应将其视为开发集。
Top-K=4 而总片段数仅为 6，Hit@4 较宽松；不能外推到长文档、大规模知识库、真实用户或高并发场景。
两轮各执行一次，问题与机器负载不同，不能据耗时差异认定性能提升或退化；没有负载测试、P95 稳定性或优化前后对照结论。

## 当前接口的最终问答评测

使用专用单文档基线知识库（脚本默认 ID=4，名称 `RAG评测_基线_v1`），仅上传 `fixtures/internship_policy.md` 并索引。
不同环境需核对 `run_current_eval.py` 中的 `BASE_URL`、`KB_ID`、名称校验和 `LIMIT`。
启动当前服务后，在已安装项目依赖的 Python 环境中执行：

```powershell
python evals/run_current_eval.py
```

用户名、密码通过交互输入，不写入脚本；输入 `RUN` 才发送真实问答请求。
默认执行 10 题，可能产生聊天模型费用并新增历史，不自动重试；请求失败会停止后续问答。
人工检查 `answer`、`expected_points` 和 `citations`；HTTP 成功不等于答案正确。
此脚本的 `elapsed_seconds` 为客户端端到端时间，与上述只检索耗时不能直接比较。

---

## 旧版共享接口评测记录（保留历史，不按此运行）

下文的 `8001`、`run_eval.py` 和结果来自旧版本。当前共享接口已停用，复现请使用上面的当前入口。

### 目的

检查回答是否符合资料、是否检索到预期来源，以及资料未提供答案时能否正确拒答。

### 文件

- cases.json：10 道固定问题及预期答案要点
- run_eval.py：请求接口并保存实际结果
- fixtures/internship_policy.md：评测使用的演示手册

手册仅用于项目演示，评测以文件内容为准，不代表真实公司制度。

### 历史运行方法（已停用）

1. 配置并启动 RAG 后端，地址为 http://127.0.0.1:8001。
2. 通过页面上传演示手册，建立索引。已有同名手册时不用重复上传。
3. 在项目根目录执行：

```powershell
python evals/run_eval.py
```

运行会调用 10 次模型接口，可能产生 API 费用，并写入问答历史。

### 结果检查

报告保存在本地 outputs/rag_eval，不提交到 Git。

- request_ok：接口请求是否成功，不代表答案正确
- answer：实际回答，需要人工对照 expected_points
- expected_source_retrieved：目标文件是否出现在检索来源中
- citations：返回的候选片段，需要检查是否支持回答
- elapsed_seconds：单次请求耗时

模型回答不要求与预期要点逐字一致。
拒答题不应编造资料中未提供的金额、天数或姓名。

### 2026-10-19 基线记录

人工核对结果：

- 请求成功：10/10
- 可回答题符合预期要点：7/7
- 可回答题检索到目标手册：7/7
- 无答案题正确拒答：3/3

这是单份短手册上的小规模评测，不代表系统整体准确率。

本轮来源列表同时包含其他检索文件，尚未验证每个候选片段是否真正支持答案。
其他知识库文件、模型及配置变化都可能影响结果。
