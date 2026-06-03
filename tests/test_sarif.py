import json

from holster_scan.report import LocatedFinding, render_sarif


def test_sarif_minimal_shape_is_valid_2_1_0():
    sarif = json.loads(
        render_sarif(
            [
                LocatedFinding(
                    package="reqeusts",
                    reason="undeclared and close to popular package requests",
                    confidence="high",
                    ecosystem="python",
                    path="app.py",
                    line=1,
                )
            ]
        )
    )

    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "holster-scan"
    assert run["tool"]["driver"]["rules"][0]["id"] == "HOLSTER001"
    result = run["results"][0]
    assert result["ruleId"] == "HOLSTER001"
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "app.py"
    assert result["locations"][0]["physicalLocation"]["region"]["startLine"] == 1
