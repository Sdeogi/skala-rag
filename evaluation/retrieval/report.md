# Retrieval 평가 결과

- Hit Rate@5: **65.00%**
- MRR@5: **0.403**
- 질의 수: 20

| id | tech | category | hit | RR | query |
|---|---|---|---|---|---|
| kivi-01 | KIVI | principle | O | 0.50 | KIVI는 Key 캐시와 Value 캐시를 각각 어떤 축으로 양자화하는가? |
| kivi-02 | KIVI | principle | O | 0.33 | KIVI가 KV 캐시를 몇 비트로 압축하는가? |
| kivi-03 | KIVI | experimental_setup | O | 0.20 | KIVI 실험에 사용된 모델은 어떤 것들인가? |
| kivi-04 | KIVI | experimental_setup | O | 1.00 | KIVI 성능 평가에 사용된 벤치마크나 태스크는 무엇인가? |
| kivi-05 | KIVI | performance | O | 1.00 | KIVI를 적용하면 메모리 사용량과 처리량(throughput)이 얼마나 개선되는가? |
| kivi-06 | KIVI | performance | X | 0.00 | KIVI의 정확도는 16비트 대비 얼마나 저하되는가? |
| kivi-07 | KIVI | limitations | O | 1.00 | KIVI에서 residual length나 group size 같은 하이퍼파라미터가 성능에 미치는 영향은? |
| kivi-08 | KIVI | limitations | X | 0.00 | KIVI는 어떤 종류의 태스크에서 평가하기 어려운가? |
| kivi-09 | KIVI | principle | X | 0.00 | KIVI에서 residual cache(잔차 캐시)는 어떤 역할을 하는가? |
| kivi-10 | KIVI | experimental_setup | O | 1.00 | KIVI의 효율성(지연시간) 평가는 어떤 방식으로 진행되었는가? |
| infinigen-01 | InfiniGen | principle | O | 0.50 | InfiniGen은 어떤 방식으로 중요한 KV를 미리 예측하고 가져오는가? |
| infinigen-02 | InfiniGen | principle | X | 0.00 | InfiniGen이 중요한 토큰을 찾기 위해 사용하는 특이값 분해(SVD) 기법은 무엇인가? |
| infinigen-03 | InfiniGen | experimental_setup | O | 0.33 | InfiniGen 실험에 사용된 모델과 파라미터 크기는? |
| infinigen-04 | InfiniGen | experimental_setup | X | 0.00 | InfiniGen의 비교 대상(baseline) 시스템은 무엇인가? |
| infinigen-05 | InfiniGen | performance | O | 0.50 | InfiniGen은 기존 방법 대비 몇 배의 속도 향상을 보이는가? |
| infinigen-06 | InfiniGen | performance | X | 0.00 | InfiniGen 적용 시 KV 캐시 사용량은 평균적으로 얼마나 줄어드는가? |
| infinigen-07 | InfiniGen | limitations | O | 0.20 | InfiniGen의 prefetching으로 인한 오버헤드는 무엇인가? |
| infinigen-08 | InfiniGen | limitations | X | 0.00 | InfiniGen이 부분 가중치(partial weight)를 압축할 수 있는 한계는 무엇인가? |
| infinigen-09 | InfiniGen | principle | O | 0.50 | InfiniGen은 KV 캐시를 어디에 저장하고 필요한 것만 어떻게 가져오는가? |
| infinigen-10 | InfiniGen | performance | O | 1.00 | 긴 문맥(long context)에서 InfiniGen의 perplexity 성능은 어떠한가? |
