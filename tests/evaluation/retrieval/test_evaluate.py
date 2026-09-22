from skala_rag.evaluation.retrieval.evaluate import run_evaluation


def test_run_evaluation_produces_report_for_all_20_questions():
    report = run_evaluation()

    assert report.k == 5
    assert len(report.results) == 20
    assert 0.0 <= report.hit_rate <= 1.0
    assert 0.0 <= report.mrr <= 1.0
    tech_names = {r.tech_name for r in report.results}
    assert tech_names == {"KIVI", "InfiniGen"}
    # 최소한의 품질 기준: 절반 이상은 상위 5개 안에서 정답 근거를 찾아야 한다.
    assert report.hit_rate >= 0.5
