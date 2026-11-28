# Quota projections never make agents stop or hold work

## Owner's words

"최근 claude transcript들 예를 들면 @thread:thr_9pjetuuxgk 스레드의 마지막 메시지를 보면 usage pace를 고려하여 작업을 스스로 중단하는 경우들을 관측하고 있습니다. 이런 동작을 원하지 않습니다." (2026-11-29 02:37 +09:00, bb thread thr_qx3s8h5msu, the opening message)

## Situation

The `worker-routing` skill asked agents to quote the `quota-pace.py` reason in every report and to carry each side's readings and projections through compaction. The script's reason quoted projected use at reset, such as "claude projects 174.9%". Agents then treated a projection above 100% as a reason to slow down. One thread's first turn after compaction reported only that Claude would reach 139% of its limit by the reset and waited. Another held three workers because Claude had 6% of room left and told its workers to save tokens.

## Scope

How agents act on weekly quota readings and projections when they start workers, run their own turns, and report to the owner. Choosing the side a worker runs on stays as it was.

## Rules out

- Deferring, shrinking, splitting, or serializing work, starting fewer workers, or asking workers to save tokens because a side is projected to run out before its reset.
- Warning the owner about a projection when no side has hit a usage limit and a side can take the work.
