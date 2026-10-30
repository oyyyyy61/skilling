# E1 long-context compaction

task=B8 budgets=12000,9000,6000,4000 repeats=3

```
strategy                 budget  n  compactions_mean  peak_tokens  retention_llm  retention_det  ret_min  ret_max  success_rate  succ_ci_low  succ_ci_high  completed_rate  violation_rate
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
uniform_summary          12000   3  1                 11614        1.0            1.0            1.0      1.0      0.0           0.0          0.56          0.67            0.0           
uniform_summary          9000    3  1                 8274         0.0            0.0            0.0      0.0      0.67          0.21         0.94          1.0             0.0           
uniform_summary          6000    3  5.3               5414         0.0            0.0            0.0      0.0      0.33          0.06         0.79          1.0             0.0           
uniform_summary          4000    3  5.7               3928         0.167          0.0            0.0      0.0      0.0           0.0          0.56          1.0             0.0           
typed_summary            12000   3  1                 11353        1.0            1.0            1.0      1.0      0.67          0.21         0.94          1.0             0.0           
typed_summary            9000    3  1                 8274         1.0            1.0            1.0      1.0      0.0           0.0          0.56          1.0             0.0           
typed_summary            6000    3  4.3               5195         1.0            1.0            1.0      1.0      1.0           0.44         1.0           1.0             0.0           
typed_summary            4000    3  6.7               3890         0.333          0.333          0.0      0.5      1.0           0.44         1.0           1.0             0.0           
typed_summary_protected  12000   3  1                 11353        1.0            1.0            1.0      1.0      0.67          0.21         0.94          1.0             0.0           
typed_summary_protected  9000    3  1                 8274         1.0            1.0            1.0      1.0      0.0           0.0          0.56          1.0             0.0           
typed_summary_protected  6000    3  4.3               5378         1.0            1.0            1.0      1.0      0.33          0.06         0.79          1.0             0.0           
typed_summary_protected  4000    3  8.7               4022         1.0            1.0            1.0      1.0      0.67          0.21         0.94          0.33            0.0           
```
