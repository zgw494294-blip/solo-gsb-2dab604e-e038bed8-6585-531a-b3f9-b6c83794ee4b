# 离线软件依赖求解 API

基于 Python + FastAPI 的**纯离线**软件依赖求解服务：求解只使用请求体中自带的 `catalog`，
**不会联网查询任何包仓库或其他外部服务**。

- 服务端口：**8000**
- 求解接口：`POST /solve`
- 冲突分析接口：`POST /conflicts`
- 健康检查：`GET /health`
- 交互式文档（服务启动后）：<http://localhost:8000/docs>

## 一、快速开始（Docker Compose）

需要已安装 Docker 与 Docker Compose 插件。一条命令即可构建镜像、安装依赖并启动服务：

```bash
docker compose up --build
```

看到类似下面的输出即表示就绪：

```text
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

之后服务监听在 <http://localhost:8000>。后台运行可用：

```bash
docker compose up --build -d
docker compose logs -f      # 查看日志
docker compose down         # 停止并移除
```

## 二、请求格式

`POST /solve`，`Content-Type: application/json`，请求体包含两个字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `catalog` | 对象 | 包目录：包名 → 版本数组。最多 **8** 个包，每个包 **1～5** 个版本。 |
| `roots` | 对象（非空） | 根约束：包名 → 正整数闭区间 `[min, max]`。 |

每个版本项包含：

- `version`：正整数版本号；同一包内不得重复。
- `dependencies`：对象，依赖包名 → 正整数闭区间 `[min, max]`，含义与 `roots` 相同，
  依赖可传递，**允许可满足的循环依赖**。

### 约束规则

- 只选择从 `roots` 出发、沿所选版本的依赖边可达的包；每个被选包恰好选择一个版本。
- 所有根约束与传递依赖的区间约束（闭区间，含端点）都必须满足。
- 同一约束下存在多个解时：把**全部包名按字典序升序排列**构成版本向量，
  未选中的包记为 `0`，取该向量**字典序最大**的解。
- 以下输入非法，返回 **HTTP 422**：
  - 区间不是两个正整数、或下界大于上界（如 `[3, 1]`、`[0, 1]`）；
  - 同一包出现重复 `version`；
  - `roots` 或任何 `dependencies` 引用了 `catalog` 中不存在的包名；
  - 包数超过 8、每包版本数不在 1～5、`roots` 为空、出现多余字段等。

### 响应

可满足：

```json
{ "satisfiable": true, "selected": { "app": 2, "lib": 3 } }
```

不可满足（冲突、无解）：

```json
{ "satisfiable": false, "selected": {} }
```

## 三、请求示例

### 示例 1：基本求解（含传递依赖、多解择优）

```bash
curl -s http://localhost:8000/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {
      "app": [
        {"version": 1, "dependencies": {"lib": [1, 2]}},
        {"version": 2, "dependencies": {"lib": [2, 3]}}
      ],
      "lib": [
        {"version": 1, "dependencies": {}},
        {"version": 2, "dependencies": {}},
        {"version": 3, "dependencies": {}}
      ]
    },
    "roots": {"app": [1, 2]}
  }'
```

候选解包括 `(app,lib) = (1,1)/(1,2)/(2,2)/(2,3)`，版本向量字典序最大者为：

```json
{"satisfiable": true, "selected": {"app": 2, "lib": 3}}
```

### 示例 2：可满足的循环依赖

```bash
curl -s http://localhost:8000/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {
      "a": [{"version": 1, "dependencies": {"b": [1, 1]}}],
      "b": [{"version": 1, "dependencies": {"a": [1, 1]}}]
    },
    "roots": {"a": [1, 1]}
  }'
```

响应：

```json
{"satisfiable": true, "selected": {"a": 1, "b": 1}}
```

### 示例 3：冲突，需要回溯后仍无解

```bash
curl -s http://localhost:8000/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {
      "app": [{"version": 1, "dependencies": {"lib": [5, 9]}}],
      "lib": [
        {"version": 1, "dependencies": {}},
        {"version": 2, "dependencies": {}}
      ]
    },
    "roots": {"app": [1, 1]}
  }'
```

响应：

```json
{"satisfiable": false, "selected": {}}
```

### 示例 4：非法区间（422）

```bash
curl -i http://localhost:8000/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {"app": [{"version": 1, "dependencies": {}}]},
    "roots": {"app": [3, 1]}
  }'
```

返回 `HTTP/1.1 422 Unprocessable Entity`，响应体说明具体校验错误。

## 四、冲突分析接口：`POST /conflicts`

请求体与 `POST /solve` **完全相同**（同样的 `catalog`、`roots`、同样的离线语义与全部
校验规则，非法输入同样返回 **HTTP 422**），区别只在响应：当原请求无解时，它会定位
最小的冲突根集合并给出“移除一个根即可解”的见证。

### 响应

原请求**可满足**时：

```json
{ "satisfiable": true, "conflict_roots": [], "witnesses": {} }
```

原请求**无解**时：

- 从所有**非空根约束子集**中，找出自身就不可满足、且**基数最小**的一组根；
  若有多组并列，取各组成员按包名升序排列后**字典序最小**的一组。
- `conflict_roots`：该组根包名（按包名升序）。
- `witnesses`：对组内每个根 `r`，以其包名为键，值为**移除 `r` 后仅用组内剩余根**
  重新求解得到的 `selected`，择优规则与 `/solve`（版本向量字典序最大）一致；
  冲突组只有一个根（剩余根为空）时，值为 `{}`。
- 由于冲突组基数最小，移除其中任意一个根后都必然可满足。

```json
{
  "satisfiable": false,
  "conflict_roots": ["cli", "web"],
  "witnesses": {
    "cli": {"web": 1, "lib": 3},
    "web": {"cli": 1, "lib": 1}
  }
}
```

### 示例：双根互相冲突

`web` 要求 `lib ∈ [2, 3]`，`cli` 要求 `lib = 1`，两个根单独都可满足、合在一起无解：

```bash
curl -s http://localhost:8000/conflicts \
  -H 'Content-Type: application/json' \
  -d '{
    "catalog": {
      "web": [{"version": 1, "dependencies": {"lib": [2, 3]}}],
      "cli": [{"version": 1, "dependencies": {"lib": [1, 1]}}],
      "lib": [
        {"version": 1, "dependencies": {}},
        {"version": 2, "dependencies": {}},
        {"version": 3, "dependencies": {}}
      ]
    },
    "roots": {"web": [1, 1], "cli": [1, 1]}
  }'
```

响应：

```json
{
  "satisfiable": false,
  "conflict_roots": ["cli", "web"],
  "witnesses": {
    "cli": {"web": 1, "lib": 3},
    "web": {"cli": 1, "lib": 1}
  }
}
```

若单个根本身不可满足（如根区间内没有任何版本），则冲突组只含该根，
响应形如 `{"satisfiable": false, "conflict_roots": ["app"], "witnesses": {"app": {}}}`。

## 五、实现说明

- `app/schemas.py`：基于 Pydantic 的请求模型与全部输入校验（失败由 FastAPI 转为 422）；
  `/solve` 与 `/conflicts` 共用同一请求模型，并各自定义响应模型。
- `app/solver.py`：回溯求解器。维护已选版本、累积区间约束和可达包集合，
  发现冲突即回溯换版；版本降序尝试并配合乐观上界做分支限界，
  找到字典序最大解后快速剪枝。`find_minimal_conflict` 在其之上按基数递增、
  包名字典序枚举根约束子集，找出最小无解集合并为每个成员求移除后的见证解。
- `app/main.py`：FastAPI 应用与 `/solve`、`/conflicts`、`/health` 路由。

## 六、本地开发与测试（不使用 Docker）

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload --port 8000
```

测试覆盖：传递依赖、循环依赖、冲突回溯、不可满足、字典序择优、各类 422 非法输入，
以及 `/conflicts` 的可满足响应、单根/多根最小冲突集、并列字典序择优、见证解择优；
另有用随机 catalog 与暴力枚举逐一比对的正确性校验（脚本不在仓库内，可用上述开发环境自行扩展）。
