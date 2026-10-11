# 学习、班级权限与判题衍生数据实施说明

本说明记录 `learning` 工作实现的确定性选择。六个 HTTP 入口以 `docs/openapi/learning-api-v1.yaml` 为准；知识点及正式标注仅使用新知识契约允许的数据。本文件不代替交付包的签字记录。

## 计算规则（elo-v1）

- 学生初值 1200；题目知识维度初值按 Low/Mid/High 映射为 1000/1200/1500，也可以由 `ProblemKnowledgeRating` 的人工难度覆盖。
- `expected = 1 / (1 + 10 ** ((problem_rating - student_rating) / 400))`。
- `delta = 32 * normalized_mapping_weight / sqrt(attempt_number) * (actual - expected)`。仅使用 approved 正式映射；每题的正权重归一化。一次提交对同题的所有知识维度共用一次 attempt_number。
- ACM 的 AC=1、WA=0、TLE/MLE/RE=0.1；CE 不更新算法知识维度。OI 按实际得分/总分计算并限制在 [0,1]。等待、判题中及系统错误不计分。
- Decimal 中间计算，四位小数 ROUND_HALF_UP 入库。掌握等级依次为 `<1000 weak`、`<1200 learning`、`<1500 stable`、其余 mastered；最近五次该维度失败至少三次时降低一级。
- 基础可信度为 `attempt_count / (attempt_count + 10)`；读取时按七天半衰期衰减可信度，保留三位小数。时间经过不直接扣 rating。
- `RatingHistory` 保存题目难度、期望分、实际分、判题结果、K、规范权重、重复衰减和输入修订号，不保存源代码、测试点或模型内容。判题结果影响已包含在 actual 中，result_weight 固定为 1。

## 幂等、重判与恢复

`LearningSubmissionEvent` 是持久事件表，按 Submission 唯一。首次采集保存当时已批准标注、题目难度和判题分值；后续映射变化不改写已有计算输入。事件的 source 记录 result、原始 score、rule_type、total_score；重判递增 revision，并在 previous_results 保留先前结果、actual、source 和 captured_time。旧事件没有采集时间时保留 null，不补造历史时间。消费时按学生的提交时间及 submission id 稳定排序重算，替换该学生的衍生画像与当前版本 RatingHistory，避免乱序消息和重判累加。历史重判输入修订仍保存在事件中。

知识写锁 → 学习计算锁 → 路径锁的顺序固定。额外的 `(submission, knowledge_point, algorithm_version)`、`(user, knowledge_point)` 唯一约束防止重复计分；同一学生只允许一条 active 路径。所有锁在事务结束释放，PG 锁等待设上限。

判题终态保存触发事件采集，事务提交后再投递 Dramatiq。正常 `Submission.save()` 会把判题状态与 outbox 采集放在同一事务；采集失败抛出脱敏的 `LearningCaptureError`，回滚本次状态与事件修订，不能留下缺少学习事件的已确认终态。Judge actor 仅对标记可恢复的采集异常额外重试最多3次；普通代码错误和其他位置的数据库错误不因此自动重试。Dramatiq 的 `retry_when` 自行检查次数上限，避免绕过 `max_retries` 形成无限重试。

终态写入阶段耗尽重试会保留 `JUDGING`；先处理锁竞争、数据库或代码问题，再由管理员在服务端执行 `python manage.py recover_judge <submission_id>` 显式重投。该命令仅接受可用用户的判题中提交，不重置已完成结果，也不保证未修复的故障能恢复。新建等待提交没有旧事件时直接跳过采集，不占知识图锁；已有事件的重判仍需保留撤回和修订。

队列投递失败时已提交事件仍保留，可由 outbox 恢复器重投。旧版缺事件、旧格式 source，或明确绕过模型 `save()` 的 `QuerySet.update()` / bulk 数据操作，仍需以下回填命令：

```sh
python manage.py recover_learning --backfill --sync --limit 1000 --settings=oj.settings
python manage.py recover_learning --user-id 1001 --settings=oj.settings
```

第一条在 SQL 中比较当前判题 source 与已采集 source，再按提交时间和 id 取 limit，补齐遗漏事件、旧格式 source 和采集失败的重判修订并消费未完成事件。已一致的早期提交不会挤占下一批，OI 同 result 下 score 改变以及 AC 被撤销为等待/系统错误均可恢复。第二条按已保存输入重算指定学生；需要同时核对当前判题时加 --backfill。应由部署调度定期执行恢复命令，不能只依赖消息队列重试。旧的未标注提交在首次采集时没有有效映射则不产生评分；后续批准标注不会静默改变历史输入。失败任务只可更新其原 revision 且尚未成功消费的事件，不能覆盖另一个任务已成功处理或较新的修订。

## 推荐（path-v1）

从目标知识点或当前薄弱/尚未掌握知识点出发，按 required 先修关系拓扑排序。每次最多五步，每个维度最多一题；选择距离学生 rating 最近且不超过学生 rating + 200 的题目，稳定同分时按展示题号排序。排除已 AC、隐藏题、比赛题、缺测试配置、缺语言、未编译成功的 SPJ 以及未审核映射。缺合适题目时保留知识复习步骤，题目字段为 null。

路径七天过期；刷新会将旧活动路径标记 superseded，持久保存输入画像与解释依据。Idempotency-Key 按用户隔离，相同参数重放、不同参数 409；普通新刷新默认十秒间隔，同一幂等请求不受重复刷新限流影响。读取和重放重新检查题目可见性，不返回后来隐藏的题目标题或编号。全部步骤完成后路径进入 completed。评分与题目步骤进度使用同一已采集事件修订，避免采集失败时混用最新判题与旧画像。重判撤销 AC 后，最新且尚未过期、知识仍活动的 completed 路径重新进入 active；旧路径、过期路径和涉及废弃知识的路径不会重新激活。复习步骤没有题目时不由判题事件自动完成。

## 班级范围

教师身份来自 active TeachingClassTeacher，不要求全站管理员身份。读取学生必须同时满足活动班级、活动教师成员、活动学生成员，越界统一 404。聚合只计本班活动且未禁用学生。管理员跨班访问必须提供 `X-Audit-Reason`，并写入 TeachingAccessEvent。

当前契约没有班级管理 HTTP 入口，采用本地管理命令合并审核后的名册；未出现在文件中的成员保持不变，离班和禁用用显式 status 表达。示例：

```json
{"code":"2026-algo-01","name":"算法一班","term":"2026-fall","teachers":[{"username":"teacher1","role":"owner"}],"students":[{"username":"student1","student_number":"001"}]}
```

```sh
python manage.py sync_teaching_class roster.json --actor admin --reason TICKET-001 --settings=oj.settings
```

全站管理员可以创建或修改班级并合并名册。已有活动班级的 active owner 也可作为审计主体合并本班学生和教师，但不能创建班级、改变班级基本字段或归档状态；普通 teacher/assistant、离任 owner 和其他班级 owner 均无修改权限。账号预先存在，重复成员、重复班内学号和非法字段拒绝，整个合并在一个事务中完成。保存班级和成员历史，不执行物理删除。

审计请求头 `X-Audit-Reason` 使用 UTF-8 百分号编码，服务端严格只解码一次。线协议只接受可打印 ASCII，编码后最多4096字节，解码后最多1000个Unicode字符；非法百分号、非法UTF-8以及C0/C1控制字符拒绝。空头等价于未提供理由，跨班级查询仍按缺失理由拒绝；合法ASCII可直接传递，但字面百分号必须编码为 `%25`。前端统一调用 `frontend/src/api/learning.js`，不要直接把中文放入请求头。

## API 与范围限制

画像按稳定知识 code 返回至多 100 个活动知识状态、班级统计至多 500 个知识点，遵循现有 v1 schema；超出这一规模需要后续分页契约。响应含真实 HTTP 状态、request_id、X-API-Version，并沿用 Django Session/CSRF。重复查询参数和未声明字段返回 400。Agent 只能读取学习服务，不注册刷新、评分或改画像工具。

开发验收记录及仍需外部环境验证的项目统一写入 `docs/plans/backend-completion-matrix.md`，不把模拟供应商测试标记为真实模型验收。
