# E1b forced-compaction experiment

```
strategy                 every  n   compactions_mean  retention_mean  retention_min  retention_max  success_rate  completed_rate  violation_rate
--------------------------------------------------------------------------------------------------------------------------------------------------
typed_summary            0      12  0                 1.0             1.0            1.0            0.83          0.92            0.0           
typed_summary            2      12  2.2               1.0             1.0            1.0            0.92          1.0             0.0           
typed_summary            4      12  0.7               1.0             1.0            1.0            0.92          0.83            0.0           
typed_summary            10     12  0.1               1.0             1.0            1.0            0.83          1.0             0.0           
typed_summary_protected  0      12  0                 1.0             1.0            1.0            0.75          1.0             0.0           
typed_summary_protected  2      12  2.5               1.0             1.0            1.0            0.83          0.83            0.0           
typed_summary_protected  4      12  0.6               1.0             1.0            1.0            1.0           0.92            0.0           
typed_summary_protected  10     12  0.1               1.0             1.0            1.0            0.92          1.0             0.0           
uniform_summary          0      12  0                 1.0             1.0            1.0            0.92          0.92            0.0           
uniform_summary          2      12  2.4               0.153           0.0            0.5            0.58          0.83            0.0           
uniform_summary          4      12  0.7               0.75            0.0            1.0            0.83          1.0             0.0           
uniform_summary          10     12  0.1               0.958           0.5            1.0            0.75          1.0             0.0           
```
