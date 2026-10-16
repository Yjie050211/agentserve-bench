from subprocess import CompletedProcess

from agentserve_bench.cli import provenance


def test_unborn_head_is_not_a_commit(monkeypatch):
    monkeypatch.setattr(
        "agentserve_bench.cli.subprocess.run",
        lambda *a, **k: CompletedProcess(a, 128, "HEAD\n", "no HEAD"),
    )
    assert provenance()["git_commit"] is None
