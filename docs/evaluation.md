# Ground-truth evaluation

A synthetic export with planted structure was run through the full pipeline. Each row compares what was planted (computed by the generator, independently of the analysis code) with what the pipeline recovered.

Result: 13 of 13 checks pass. Era boundaries: precision 1.0, recall 1.0 (match within one month).

| Check | Planted | Recovered | Result |
|---|---|---|---|
| Raw records read | 39277 | 39277 | pass |
| Exact duplicates removed | 40 | 40 | pass |
| Podcast episodes excluded | 801 | 801 | pass |
| Music records kept | 38436 | 38436 | pass |
| Music minutes | 87270.3 | 87270.3 | pass |
| Travel-week records on Asia/Tokyo time | 219 | 219 | pass |
| Era boundaries recovered (within 1 month) | ['2022-11', '2023-08', '2024-04', '2024-12'] | ['2022-11', '2023-08', '2024-04', '2024-12'] | pass |
| Comeback artist | Golden Echoes | Golden Echoes | pass |
| Comeback return month | 2024-04 | 2024-04 | pass |
| Biggest day | 2023-11-02 | 2023-11-02 | pass |
| Peak 3-hour window starts | 18 | 18 | pass |
| Top artist | Lunar Season | Lunar Season | pass |
| Longest artist streak (days) | 213 | 213 | pass |
