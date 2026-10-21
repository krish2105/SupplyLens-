# Reference policy-change case (SYNTHETIC)

Spec chapter 4 "A concrete reference scenario", encoded as fictional documents for the Demo
workspace. Supplier A: USD 5/unit, MOQ 20, multiples of 10; amendment effective 2026-10-20
(known 2026-10-15) raises MOQ to 40. Supplier B: USD 6/unit, MOQ 10, multiples of 5.
Need 30 units by 2026-10-22, budget USD 180, nothing on hand or inbound.

Expected: decision on 2026-10-19 -> A 30 units USD 150; on 2026-10-20 -> B 30 units USD 180.
The JSON fixture in ../policy_change_case.json states slightly different dates/MOQs with the
same expected outcomes; both are covered by tests/test_planner_fixture.py.
