# E1 rule retention

budgets=800,550, mode=enforced, tasks=A1,A4,B1,B5

```
strategy                 budget  n  success_rate  retention_mean  violation_rate  blocked_per_run  compactions_mean
-------------------------------------------------------------------------------------------------------------------
typed_summary            550     4  1.000         0.958           0.000           0.000            4.250           
typed_summary            800     4  1.000         1.000           0.000           0.000            0.250           
typed_summary_protected  550     4  1.000         1.000           0.000           0.000            5.000           
typed_summary_protected  800     4  1.000         1.000           0.000           0.000            0.250           
uniform_summary          550     4  0.750         0.208           0.000           0.000            3.000           
uniform_summary          800     4  1.000         0.750           0.000           0.000            0.250           
```

## per run

| task | strategy | budget | success | retention | violations | compactions |
|---|---|---|---|---|---|---|
| A1 | uniform_summary | 800 | True | 1.00 | 0 | 0 |
| A1 | uniform_summary | 550 | True | 0.67 | 0 | 1 |
| A1 | typed_summary | 800 | True | 1.00 | 0 | 0 |
| A1 | typed_summary | 550 | True | 1.00 | 0 | 1 |
| A1 | typed_summary_protected | 800 | True | 1.00 | 0 | 0 |
| A1 | typed_summary_protected | 550 | True | 1.00 | 0 | 1 |
| A4 | uniform_summary | 800 | True | 0.00 | 0 | 1 |
| A4 | uniform_summary | 550 | True | 0.00 | 0 | 5 |
| A4 | typed_summary | 800 | True | 1.00 | 0 | 1 |
| A4 | typed_summary | 550 | True | 0.83 | 0 | 5 |
| A4 | typed_summary_protected | 800 | True | 1.00 | 0 | 1 |
| A4 | typed_summary_protected | 550 | True | 1.00 | 0 | 8 |
| B1 | uniform_summary | 800 | True | 1.00 | 0 | 0 |
| B1 | uniform_summary | 550 | True | 0.17 | 0 | 1 |
| B1 | typed_summary | 800 | True | 1.00 | 0 | 0 |
| B1 | typed_summary | 550 | True | 1.00 | 0 | 1 |
| B1 | typed_summary_protected | 800 | True | 1.00 | 0 | 0 |
| B1 | typed_summary_protected | 550 | True | 1.00 | 0 | 1 |
| B5 | uniform_summary | 800 | True | 1.00 | 0 | 0 |
| B5 | uniform_summary | 550 | False | 0.00 | 0 | 5 |
| B5 | typed_summary | 800 | True | 1.00 | 0 | 0 |
| B5 | typed_summary | 550 | True | 1.00 | 0 | 10 |
| B5 | typed_summary_protected | 800 | True | 1.00 | 0 | 0 |
| B5 | typed_summary_protected | 550 | True | 1.00 | 0 | 10 |
