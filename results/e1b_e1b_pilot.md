# E1b forced-compaction experiment

```
strategy                 every  n  compactions_mean  retention_mean  retention_min  retention_max  success_rate  completed_rate  violation_rate
-------------------------------------------------------------------------------------------------------------------------------------------------
typed_summary_protected  0      2  0                 1.0             1.0            1.0            1.0           1.0             0.0           
typed_summary_protected  2      2  2.5               1.0             1.0            1.0            1.0           1.0             0.0           
typed_summary_protected  4      2  1                 1.0             1.0            1.0            1.0           1.0             0.0           
typed_summary_protected  10     2  0.5               1.0             1.0            1.0            0.5           0.5             0.0           
uniform_summary          0      2  0                 1.0             1.0            1.0            0.5           1.0             0.0           
uniform_summary          2      2  3                 0.0             0.0            0.0            0.5           0.5             0.0           
uniform_summary          4      2  1                 0.5             0.0            1.0            0.5           1.0             0.0           
uniform_summary          10     2  0.5               0.583           0.17           1.0            1.0           1.0             0.0           
```
