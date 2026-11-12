# 01-feedstitch（信汇）

Feedstitch — 多源目录/价目 Feed 归并落库：解析 → 业务键去重/冲突隔离 → 按源水位线增量或全量落库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5100 |
| API | http://localhost:10100 |

## 主链

配置源与夹具 → 触发 Run → 解析 / 去重 / 冲突隔离 → Canonical + 行级血缘 + 运行报告对账

## 行级血缘

每次成功写入/更新 Canonical 都会追加一条 `lineage_events`：业务键、源、run、
source_revision、事件时间、写入时间，并用 `previous_lineage_id` 串成时间序链；
`canonical_items.run_id` / `canonical_items.lineage_id` 指向当前有效行对应的最新成功血缘。

- 接口：`GET /api/lineage/{business_key}`（血缘链）、`GET /api/runs/{run_id}/lineage`（run 对账）、
  `GET /api/lineage/summary`（全局计数）。
- 冲突隔离行保留来源 run/源/revision，并携带 existing 侧来源与血缘指针；它作为
  `quarantined` 节点出现在链路视图里，`applied=false`，不计入成功写入血缘。
- 运行报告新增 `lineage_event_count` / `lineage_distinct_keys` / `lineage_reconciles` /
  `canonical_lineage_pointers_ok`，与 `upserted_count` 互相解释。

## 种子说明

- **Alpha Catalog（clean）**：JSON，三件干净货号，增量可落库。
- **Beta Offers（dirty）**：JSONL，含与 Alpha 同键但价格不同的冲突行，以及迟到低 revision 行（底座增量会因水位线跳过）。
- **Gamma Shelf（xml）**：简易 XML，两件独立货号。

打开“运行台”选源跑一次增量，再看 Staging / 冲突 / Canonical 三页计数是否与本次 Run 报告一致；
运行台报告中的“本 run 新增成功血缘”应等于 `upserted`，并可点击业务键跳到“血缘追溯”页。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现）

`lookback_backfill` / `schema_drift_guard` / `dead_letter_replay` / `webhook_push_source` /
`source_authority_rank` / `tombstone_retire` / `scd2_history` / `watermark_commit_gate` /
`field_map_transform`
