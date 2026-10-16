# AgentServe Bench

**Reproducible agent-workload replay and prefix-cache benchmarking for vLLM.**

面向 Agent 多轮请求的轨迹校验、会话回放和缓存实验工具。当前交付 CPU 可运行框架、严格请求协议、真实 HTTP/SSE 适配和失败保留；**未完成真实 GPU、缓存冷/热状态校准或性能收益验证**。本仓库不是推理引擎，也不实现 Agent Loop。

## 快速开始（CPU，无模型下载）

要求 Python 3.11 和 [uv](https://docs.astral.sh/uv/)。

```sh
uv sync --frozen
uv run agentserve synthetic --output results/trace-demo
uv run agentserve validate results/trace-demo/model_requests.jsonl
uv run agentserve prefix results/trace-demo/model_requests.jsonl
uv run agentserve replay results/trace-demo/model_requests.jsonl --backend fixture --concurrency 2 --output results/run-demo
uv run pytest
uv run ruff check .
```

每个输出目录必须不存在，避免覆盖实验。Fixture 的时间与 Token 数据是协议测试数据，报告标记 `execution_mode=fixture`；不用于证明 GPU 性能。`prefix` 使用确定性的 UTF-8 字节编码验证前缀算法，输出明确标记为 fixture units，不是实际模型 Token 或缓存命中。

## 数据流

```text
synthetic / Harness model_requests.jsonl + wire body artifacts
    -> schema / hash / session validation
    -> source attempt selection + original records
    -> bounded concurrent sessions, in-session ordered replay
    -> raw SSE events + typed observations + per-request results
    -> summary.json + report.md
```

源数据默认只选择完整、有效、成功的逻辑调用，所有源尝试和筛选原因保存在 `source_selection.jsonl`。实验中失败不删除、不自动重试；一个会话失败后，后续步骤标记 `not_sent`，其他会话继续。冻结回放下一步来自固定轨迹，不能得出真实 Agent 任务成功率。

## 导入 AgentHarness-Lab

不依赖另一个仓库的 Python 包，使用版本为 `1.0` 的文件协议：

```sh
uv run agentserve validate /path/to/harness-run/model_requests.jsonl
uv run agentserve replay /path/to/harness-run/model_requests.jsonl --origin harness_export --backend fixture --output results/harness-fixture-run
```

传入原始 JSONL 路径，保留其引用的相对 body artifacts。源真实调用必须有 wire body 与哈希；fake 源缺少 wire 时允许明确标记为 canonical reconstruction，不称字节原样回放。详见 [schema 来源](schemas/UPSTREAM.md)。

## 真实 vLLM HTTP（需已有服务器）

本工具不启动/重启服务器、不下载模型、不修改缓存配置。Windows 主机访问 Linux/WSL 上已部署的 vLLM endpoint。将下面版本和模型换成实际环境，版本必须与 `/version` 返回完全一致：

```sh
uv run agentserve inspect --base-url http://127.0.0.1:8000/v1 --expected-version YOUR_INSTALLED_VERSION
uv run agentserve replay results/trace-demo/model_requests.jsonl --backend http --base-url http://127.0.0.1:8000/v1 --expected-version YOUR_INSTALLED_VERSION --model YOUR_SERVED_MODEL --body-mode stream --output results/http-run
```

API key 只从 `AGENTSERVE_API_KEY` 环境变量读取，不写入产物。`--model` 映射和 `--body-mode stream` 的参数变更逐条保存，原始 body 与实际发送 body 分开记录。默认 `preserve` 不修改源请求；非流式请求只能获得端到端时延。包含工具历史的真实回放须显式加 `--probe-tools`，先验证 tools 与 assistant/tool 历史可被接受；探针会影响缓存，不能称后续批次开始冷缓存。

HTTP 协议成功并不证明 GPU 已验收；当前报告的 `real_gpu_validated` 维持 false。客户端超时也不意味着服务端已停止，必须核对服务端 running/waiting 并排空后才能进入下一次受控实验。

## 缓存矩阵的当前边界

```sh
uv run agentserve plan-matrix --config configs/prefix_matrix.yaml
```

该命令只生成实验计划，**不生成测量结果**。能力模块提供版本检查、原始 Prometheus 快照、排空检查、带单位/独占窗口约束的计数差分。reset HTTP 200 只作为响应记录，永远不单独判定冷缓存。真正的 off/on × 批次开始冷缓存/固定前缀预热实验需要先实现并验收指定 vLLM 版本的缓存重置校准；当前不自动执行。

## 产物与验证

每次回放保存 manifest、源尝试筛选、原始/有效请求 body、逐请求原始与类型化事件、results、summary 和 Markdown 报告。manifest 包含锁文件哈希、Git revision、运行环境、来源与模式。长日志默认忽略，不提交密钥或私有原始轨迹。

CI 仅运行 CPU 测试、CLI smoke 和构建，不要求 GPU 或模型。当前能力及测试证据见 [results](docs/results.md)；[指标口径](docs/metrics.md)、[实验协议](docs/experiment_protocol.md)、[架构](docs/architecture.md)。

## 归属

原创代码 MIT。请求 schema 的唯一维护源为 [AgentHarness-Lab](https://github.com/Yjie050211/agent-harness-lab)，本仓库固定快照；黄金指标样例与 NanoServe-Lab 对齐。真实服务由上游 [vLLM](https://github.com/vllm-project/vllm) 提供，本仓库不复制其引擎或宣称推理算法原创。
