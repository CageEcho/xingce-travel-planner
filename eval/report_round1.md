# 评测报告 · 第 1 轮（真实模型，存档）

由 `eval/run.py` 自动生成，数字均为本次实际跑测结果。

## 核心指标

| 指标 | 结果 |
| --- | --- |
| 用例数 | 30（评分 30，dry-run 跳过 0） |
| 通过率 | 27/30 = 90% |
| 硬约束违规（blocking）总数 | 13 |
| 方案一次通过率（首轮即零硬约束违规） | 11/19 = 58% |
| 关键需求项识别准确率 | 46/46 = 100% |

## 五维评分（0–100，规则化自动打分）

| 维度 | 均分 | 评分口径 |
| --- | --- | --- |
| 需求理解 | 100.0 | 抽取用例：期望槽位 + 应留空槽位 + 必须追问项的逐项命中率；冲突用例：预期冲突是否全部检出 |
| 资源召回 | 100.0 | 每城酒店/餐厅/景点候选 ≥3 的覆盖率 ×70 + 方案景点命中客户兴趣标签 ×30 |
| 事实准确性 | 89.5 | 引用校验拦截即 0 分；陷阱资源 −50、空值或待校验资源未进清单 −25、推荐理由含数字 −25 |
| 行程合理性 | 88.2 | 最终硬约束违规每项 −25；轮椅客人用到不可达景点 −10 |
| 方案完整度 | 92.1 | 天数不足 −30、缺住宿每天 −20、内容过少每天 −10、预约门票未提醒 −20、无产品推荐 −10、清单缺核实说明 −10 |

## Bad Case 归因

| 归因 | 用例数 |
| --- | --- |
| 行程冲突 | 3 |

## 逐条结果

| 用例 | 用例族 | 结果 | 重排轮次 | 待核实 | 需求理解 | 资源召回 | 事实准确性 | 行程合理性 | 方案完整度 | 失败原因 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| accessible_hakone_23 | hard_constraint_trap | 通过 | 0 | 3 | — | 100 | 100 | 100 | 100 | — |
| anime_ticket_21 | knowledge_coverage | 通过 | 0 | 1 | — | 100 | 100 | 100 | 100 | — |
| budget_tier_conflict_13 | budget_conflict | 通过 | — | 0 | 100 | — | — | — | — | — |
| cross_city_commute_08 | hard_constraint_trap | 通过 | 2 | 7 | — | 100 | 100 | 100 | 100 | — |
| days_cities_conflict_14 | budget_conflict | 通过 | — | 0 | 100 | — | — | — | — | — |
| extract_budget_basis_18 | slot_extraction | 通过 | — | 0 | 100 | — | — | — | — | — |
| extract_euphemism_17 | slot_extraction | 通过 | — | 0 | 100 | — | — | — | — | — |
| extract_family_16 | slot_extraction | 通过 | — | 0 | 100 | — | — | — | — | — |
| extract_locked_slots_20 | slot_extraction | 通过 | — | 0 | 100 | — | — | — | — | — |
| extract_no_guess_19 | slot_extraction | 通过 | — | 0 | 100 | — | — | — | — | — |
| extract_per_person_29 | slot_extraction | 通过 | — | 0 | 100 | — | — | — | — | — |
| extract_vague_japan_28 | slot_extraction | 通过 | — | 0 | 100 | — | — | — | — | — |
| extract_wheelchair_30 | slot_extraction | 通过 | — | 0 | 100 | — | — | — | — | — |
| family_kyoto_01 | hard_constraint_trap | 通过 | 1 | 0 | 100 | 100 | 100 | 100 | 100 | — |
| family_ryokan_child_02 | hard_constraint_trap | 通过 | 0 | 0 | 100 | 100 | 100 | 100 | 100 | — |
| governance_pending_22 | knowledge_coverage | 通过 | 0 | 1 | — | 100 | 100 | 100 | 100 | — |
| hakone_family_03 | hard_constraint_trap | 通过 | 0 | 2 | — | 100 | 100 | 100 | 100 | — |
| halal_shortage_25 | null_handling | 失败 | 2 | 3 | — | 100 | 100 | 75 | 100 | blocking=1 [H3 D2 RST-HKN-012: 2026-11-11 是周三，该资源当日休息] |
| honeymoon_ryokan_27 | knowledge_coverage | 通过 | 2 | 1 | — | 100 | 100 | 100 | 70 | — |
| large_family_luggage_07 | hard_constraint_trap | 失败 | 2 | 4 | — | 100 | 0 | 0 | 60 | blocking=4 [REF D5 HTL-KYO-004: 引用校验拦截（id_not_in_pool）：HTL-KYO-004 不在本次检索候选池; REF D6 HTL-KYO-004: 引用校验拦截（id_not_in_pool）：HTL-KYO-004 不在本次检索候选池; S1 D5 -: 当日缺少可用住 |
| monday_museum_05 | hard_constraint_trap | 通过 | 2 | 1 | — | 100 | 100 | 100 | 100 | — |
| null_child_age_10 | null_handling | 通过 | 0 | 2 | — | 100 | 100 | 100 | 100 | — |
| null_dietary_support_09 | null_handling | 通过 | 0 | 0 | — | 100 | 100 | 100 | 100 | — |
| null_reference_price_11 | null_handling | 通过 | 0 | 0 | — | 100 | 100 | 100 | 100 | — |
| null_vehicle_luggage_12 | null_handling | 通过 | 0 | 0 | — | 100 | 100 | 100 | 100 | — |
| room_pax_conflict_15 | budget_conflict | 通过 | — | 0 | 100 | — | — | — | — | — |
| three_city_family_26 | hard_constraint_trap | 失败 | 2 | 1 | — | 100 | 0 | 0 | 20 | blocking=8 [REF D4 HTL-HKN-001: 引用校验拦截（id_not_in_pool）：HTL-HKN-001 不在本次检索候选池; REF D5 HTL-HKN-001: 引用校验拦截（id_not_in_pool）：HTL-HKN-001 不在本次检索候选池; REF D6 HTL-KYO-0 |
| tokyo_couple_luxury_04 | hard_constraint_trap | 通过 | 0 | 1 | 100 | 100 | 100 | 100 | 100 | — |
| tuesday_restaurant_06 | hard_constraint_trap | 通过 | 2 | 0 | — | 100 | 100 | 100 | 100 | — |
| vegan_tokyo_24 | hard_constraint_trap | 通过 | 0 | 5 | — | 100 | 100 | 100 | 100 | — |
