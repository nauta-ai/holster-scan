from holster_scan import detector


def test_synthetic_corpus_locks_gate_numbers():
    maintained_real = {"chromadb-client", "fastapi-utils"}

    def exists(name: str):
        return name in maintained_real

    def maintained(name: str) -> bool:
        return name in maintained_real

    declared = set(detector.NEGATIVE_IMPORTS)
    pos_findings = detector.detect(
        detector.POSITIVE_CORPUS,
        declared,
        registry_exists=exists,
        maintenance_check=maintained,
    )
    neg_findings = detector.detect(
        detector.NEGATIVE_IMPORTS,
        declared,
        registry_exists=exists,
        maintenance_check=maintained,
    )

    pos_hit = {finding.package for finding in pos_findings}
    neg_hit = {finding.package for finding in neg_findings}

    assert len(pos_hit) == 36
    assert {"chromadb-client", "fastapi-utils"} == set(detector.POSITIVE_CORPUS) - pos_hit
    assert round(len(pos_hit) / len(detector.POSITIVE_CORPUS), 2) >= 0.95
    assert neg_hit == set()
