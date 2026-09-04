# Eval fleet — current serving map

| Workload | Model series | Mode | Fallback |
| --- | --- | --- | --- |
| Halcyon cycle operators | `gmp-3.1-0412` | autonomous | none until next week's image rollout |
| report summarizers | `gmp-3.0-0328` | monitored | `gmp-2.9-0210` |

If a series enters restricted review, the scheduler drains its autonomous
workers at the next governance sync and archives their active queue state. The
cycle is resumed by a monitored replacement when one is available.
