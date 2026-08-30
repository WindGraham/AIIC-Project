"""回归语料 — 双 agent 互聊 harness 的小型真实感测试集。

每组 case 是 (resume_text, jd_text, company, position, level) + 候选人 profile
参数（style/strength/off_topic_prob 等）。runner 据此构建 InterviewContext 并
跑一场 mock-brain self-play，产出回归语料（transcript/scorecard/report/metrics）。

换 profile（百变候选人）或换 prompt 后重跑同批，即可量化对比退步。
"""

# ---------------------------------------------------------------------------
# Case 1: 字节跳动 · 后端开发实习生（应届 / junior）
# ---------------------------------------------------------------------------
CASE_BYTEDANCE_INTERN = {
    "id": "case001-bytedance-backend-intern",
    "company": "字节跳动",
    "position": "后端开发实习生（电商方向）",
    "level": "junior",
    "jd_text": (
        "岗位职责：参与抖音电商订单/库存等核心链路的后端开发；负责需求拆解、接口设计与联调；"
        "参与系统性能优化与线上问题排查。任职要求：本科及以上在读，计算机相关专业；扎实的计算机"
        "基础（数据结构、操作系统、网络）；熟悉 Go 或 Java，了解 Redis/MySQL；有较强的学习能力"
        "与自驱力，对电商业务有好奇心者优先。"
    ),
    "must_have": ["Go 或 Java 基础", "数据结构与算法", "Redis/MySQL 基础", "计算机网络基础"],
    "nice_to_have": ["熟悉 Kafka/RPC 框架", "有电商或交易类项目经验", "开源项目参与经历"],
    "tech_stack": ["Go", "Java", "Redis", "MySQL", "RPC", "Kafka"],
    "responsibilities": ["订单/库存链路开发", "接口设计联调", "性能优化与问题排查"],
    "resume_text": (
        "林晓雨，计算机科学与技术专业大三在读。熟悉 Python/Go，了解 MySQL/Redis，常用 Docker 部署。"
        "项目一：校园二手交易平台（Go + Gin + MySQL + Redis），负责商品模块与订单模块，用 Redis 缓存"
        "热点商品、计数器扣库存，压测 QPS 从 200 提升到 1200。项目二：简易 KV 存储（C++），实现 WAL "
        "日志与内存跳表，支持崩溃恢复。LeetCode 刷题 260+，校赛算法银牌。"
    ),
    "profile": {
        "name": "林晓雨",
        "style": "concise",
        "strength": "strong",
        "resume_skills": ["Go", "Python", "MySQL", "Redis", "Docker", "C++"],
        "off_topic_prob": 0.0,
    },
}

# ---------------------------------------------------------------------------
# Case 2: 美团 · 后端开发工程师（到店履约 / mid）
# ---------------------------------------------------------------------------
CASE_MEITUAN_BACKEND = {
    "id": "case002-meituan-backend-engineer",
    "company": "美团",
    "position": "后端开发工程师（到店履约）",
    "level": "mid",
    "jd_text": (
        "岗位职责：负责到店餐饮履约核心系统（下单、排号、核销）的设计与开发；对高并发、分布式场景"
        "下的稳定性负责，参与容量评估与限流降级方案。任职要求：3 年以上后端开发经验，Java 基础扎实；"
        "熟悉 Spring 生态、MySQL 调优、Redis、Kafka 等常用组件；理解分布式事务与最终一致性，有"
        "线上问题排查经验；具备良好的系统设计意识与责任心。"
    ),
    "must_have": ["Java/Spring 生态", "MySQL 调优", "Redis", "Kafka", "分布式事务与最终一致性"],
    "nice_to_have": ["了解 DDD 与微服务拆分", "有餐饮/零售行业经验", "熟悉 Apollo/配置中心"],
    "tech_stack": ["Java", "Spring Boot", "MySQL", "Redis", "Kafka", "Nacos"],
    "responsibilities": ["履约核心系统设计开发", "高并发稳定性治理", "容量评估与限流降级"],
    "resume_text": (
        "张伟，3 年后端开发经验，Java/Spring Boot 技术栈。项目：外卖订单系统（日单量 30 万），负责"
        "下单链路与库存扣减：引入 Redis 预扣 + MySQL 对账，将超卖率降到 0；用本地消息表 + RocketMQ "
        "实现订单状态最终一致，故障恢复时间从 40 分钟降到 5 分钟。主导一次大促容量评估，通过压测发现"
        "DB 连接池瓶颈并优化连接复用，峰值 QPS 提升 60%。"
    ),
    "profile": {
        "name": "张伟",
        "style": "verbose",
        "strength": "mid",
        "resume_skills": ["Java", "Spring Boot", "MySQL", "Redis", "RocketMQ", "Kafka"],
        "off_topic_prob": 0.1,
    },
}

# ---------------------------------------------------------------------------
# Case 3: 蚂蚁集团 · 高级后端工程师（支付核心 / senior）
# ---------------------------------------------------------------------------
CASE_ANT_SENIOR = {
    "id": "case003-ant-senior-backend",
    "company": "蚂蚁集团",
    "position": "高级后端工程师（支付核心链路）",
    "level": "senior",
    "jd_text": (
        "岗位职责：负责支付核心链路（交易、账务、清结算）的系统设计与研发，保障资金安全与高可用；"
        "推动存储选型、异地多活、容量规划等基础设施演进；指导初中级同学。任职要求：5 年以上后端研发"
        "经验，精通 Java 与常用中间件；深入理解分布式系统（一致性、幂等、对账）、数据库内核或存储"
        "引擎原理优先；有大型高并发系统架构经验，能独立完成复杂系统设计并落地。"
    ),
    "must_have": ["Java 与分布式系统原理", "一致性/幂等/对账设计", "高并发架构经验", "存储或数据库原理"],
    "nice_to_have": ["异地多活建设经验", "账务/清结算领域知识", "参与过开源中间件"],
    "tech_stack": ["Java", "RPC", "MySQL", "OceanBase", "Kafka", "Paxos/Raft"],
    "responsibilities": ["支付核心链路设计研发", "资金安全与高可用保障", "基础设施演进与团队指导"],
    "resume_text": (
        "陈哲，8 年后端研发，近 5 年在支付/账务领域。主导支付交易系统重构：将单库拆分为按商户维度"
        "分库分表，链路 P99 从 380ms 降到 95ms；设计基于状态机的交易幂等框架，资金差错率降到 0.3ppm；"
        "推进同城双活到异地多活（单元化）改造，实现 RTO < 30s。自研过小型存储引擎（LSM 树、WAL），"
        "对 MySQL InnoDB 与 OceanBase 有源码级理解。带过 4 人小组，负责核心链路 Code Review 与容量规划。"
    ),
    "profile": {
        "name": "陈哲",
        "style": "concise",
        "strength": "strong",
        "resume_skills": ["Java", "分布式系统", "MySQL", "OceanBase", "Kafka", "Paxos/Raft", "存储引擎"],
        "off_topic_prob": 0.0,
    },
}

CASES = [CASE_BYTEDANCE_INTERN, CASE_MEITUAN_BACKEND, CASE_ANT_SENIOR]

CASE_INDEX = {c["id"]: c for c in CASES}
