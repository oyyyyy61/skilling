# E1 rule retention

budget=1200 tokens, mode=enforced, tasks=A1

```
strategy                 mode      n  success_rate  retention_mean  violation_rate  blocked_per_run  compactions_mean
---------------------------------------------------------------------------------------------------------------------
truncate                 enforced  1  1.000         1.000           0.000           0.000            0.000           
typed_summary_protected  enforced  1  1.000         1.000           0.000           0.000            0.000           
```

## per run

| task | strategy | success | retention | violations | compactions |
|---|---|---|---|---|---|
| A1 | truncate | True | 1.00 | 0 | 0 |
| A1 | typed_summary_protected | True | 1.00 | 0 | 0 |
