import json
import tempfile
from pathlib import Path

import pytest

from pr_triage_agent.evaluation.run_eval import (
    EvalResult,
    build_results_table,
    compute_metrics,
    load_dataset,
    _paths_match,
    _tokenize_keywords,
)


class TestTokenizeKeywords:
    def test_basic_tokenization(self):
        tokens = _tokenize_keywords("This is a test for credential leak")
        assert "test" in tokens
        assert "credential" in tokens
        assert "leak" in tokens
        assert "is" not in tokens
        assert "a" not in tokens

    def test_empty_text(self):
        assert _tokenize_keywords("") == set()

    def test_short_words_filtered(self):
        tokens = _tokenize_keywords("in on at by cat")
        assert "cat" in tokens
        assert "in" not in tokens

    def test_hyphenated_words_split(self):
        tokens = _tokenize_keywords("credential-leak, parsing error!")
        assert "credential" in tokens
        assert "leak" in tokens
        assert "parsing" in tokens
        assert "error" in tokens

    def test_stopwords_removed(self):
        tokens = _tokenize_keywords("the and or for not with")
        assert len(tokens) == 0


class TestPathsMatch:
    def test_exact_match(self):
        assert _paths_match("src/app.py", "src/app.py")

    def test_os_separator_normalized(self):
        assert _paths_match("src\\app.py", "src/app.py")

    def test_case_insensitive(self):
        assert _paths_match("SRC/App.py", "src/app.py")

    def test_suffix_match(self):
        assert _paths_match("project/src/app.py", "src/app.py")

    def test_no_match(self):
        assert not _paths_match("src/app.py", "src/other.py")


class TestEvalResult:
    def test_precision_only_tp(self):
        r = EvalResult(pr_id="test", title="", repo="", pr_number=1, ground_truth_count=2)
        r.true_positives = [{"file": "a.py"}]
        r.false_positives = []
        assert r.precision == 1.0

    def test_precision_mixed(self):
        r = EvalResult(pr_id="test", title="", repo="", pr_number=1, ground_truth_count=2)
        r.true_positives = [{"file": "a.py"}]
        r.false_positives = [{"file": "b.py"}]
        assert r.precision == 0.5

    def test_precision_no_positives(self):
        r = EvalResult(pr_id="test", title="", repo="", pr_number=1, ground_truth_count=2)
        assert r.precision == 0.0

    def test_recall_all_found(self):
        r = EvalResult(pr_id="test", title="", repo="", pr_number=1, ground_truth_count=2)
        r.true_positives = [{"file": "a.py"}, {"file": "b.py"}]
        r.false_negatives = []
        assert r.recall == 1.0

    def test_recall_half(self):
        r = EvalResult(pr_id="test", title="", repo="", pr_number=1, ground_truth_count=2)
        r.true_positives = [{"file": "a.py"}]
        r.false_negatives = [{"file": "b.py"}]
        assert r.recall == 0.5

    def test_f1_perfect(self):
        r = EvalResult(pr_id="test", title="", repo="", pr_number=1, ground_truth_count=1)
        r.true_positives = [{"file": "a.py"}]
        assert r.f1 == 1.0

    def test_f1_no_overlap(self):
        r = EvalResult(pr_id="test", title="", repo="", pr_number=1, ground_truth_count=1)
        assert r.f1 == 0.0


class TestComputeMetrics:
    def test_exact_match(self):
        ground_truth = [
            {"file": "src/app.py", "severity": "high", "description": "credential leak via netloc parsing"},
        ]
        agent_comments = [
            {"file": "src/app.py", "comment": "credentials leak in netloc parsing", "severity": "high"},
        ]
        tp, fp, fn = compute_metrics(ground_truth, agent_comments)
        assert len(tp) == 1
        assert len(fp) == 0
        assert len(fn) == 0

    def test_partial_match(self):
        ground_truth = [
            {"file": "src/app.py", "severity": "high", "description": "credential leak via netloc parsing"},
        ]
        agent_comments = [
            {"file": "src/app.py", "comment": "credentials leak", "severity": "medium"},
        ]
        tp, fp, fn = compute_metrics(ground_truth, agent_comments)
        assert len(tp) >= 1

    def test_no_match(self):
        ground_truth = [
            {"file": "src/app.py", "severity": "high", "description": "credential leak in auth"},
        ]
        agent_comments = [
            {"file": "src/other.py", "comment": "unrelated formatting issue", "severity": "low"},
        ]
        tp, fp, fn = compute_metrics(ground_truth, agent_comments)
        assert len(tp) == 0
        assert len(fp) == 1
        assert len(fn) == 1

    def test_multiple_issues_matched(self):
        ground_truth = [
            {"file": "src/a.py", "severity": "high", "description": "sql injection risk"},
            {"file": "src/b.py", "severity": "medium", "description": "missing error handling"},
        ]
        agent_comments = [
            {"file": "src/a.py", "comment": "sql injection vulnerability detected", "severity": "high"},
            {"file": "src/b.py", "comment": "no try-except for file operations", "severity": "medium"},
        ]
        tp, fp, fn = compute_metrics(ground_truth, agent_comments)
        assert len(tp) == 2
        assert len(fp) == 0
        assert len(fn) == 0

    def test_false_positive_extra_comment(self):
        ground_truth = [
            {"file": "src/a.py", "severity": "high", "description": "credential leak"},
        ]
        agent_comments = [
            {"file": "src/a.py", "comment": "credential leak via netloc parsing", "severity": "high"},
            {"file": "src/a.py", "comment": "minor style issue", "severity": "low"},
        ]
        tp, fp, fn = compute_metrics(ground_truth, agent_comments)
        assert len(tp) == 1
        assert len(fp) == 1
        assert len(fn) == 0

    def test_false_negative_missed(self):
        ground_truth = [
            {"file": "src/a.py", "severity": "high", "description": "credential leak"},
            {"file": "src/b.py", "severity": "medium", "description": "missing validation"},
        ]
        agent_comments = [
            {"file": "src/a.py", "comment": "credential leak", "severity": "high"},
        ]
        tp, fp, fn = compute_metrics(ground_truth, agent_comments)
        assert len(tp) == 1
        assert len(fp) == 0
        assert len(fn) == 1
        assert fn[0]["file"] == "src/b.py"

    def test_empty_agent_comments(self):
        ground_truth = [{"file": "a.py", "severity": "high", "description": "security issue"}]
        tp, fp, fn = compute_metrics(ground_truth, [])
        assert len(tp) == 0
        assert len(fp) == 0
        assert len(fn) == 1

    def test_empty_ground_truth(self):
        tp, fp, fn = compute_metrics([], [{"file": "a.py", "comment": "something", "severity": "low"}])
        assert len(tp) == 0
        assert len(fp) == 1
        assert len(fn) == 0


class TestBuildResultsTable:
    def test_empty_results(self, tmp_path):
        table = build_results_table([], tmp_path / "out.md")
        assert "Evaluation Results" in table
        assert "0 PRs evaluated" in table

    def test_single_result(self, tmp_path):
        r = EvalResult(
            pr_id="test-1", title="Fix bug", repo="org/repo",
            pr_number=42, ground_truth_count=2,
        )
        r.true_positives = [{"file": "a.py"}]
        r.false_positives = [{"file": "b.py"}]
        r.false_negatives = [{"file": "c.py"}]
        r.agent_risk_rating = "high"
        r.agent_confidence = 0.85
        r.runtime_seconds = 5.2

        table = build_results_table([r], tmp_path / "out.md")
        assert "test-1" in table
        assert "org/repo" in table
        assert "Fix bug" in table
        assert "high" in table
        assert "0.85" in table

    def test_multiple_results_precision_recall(self, tmp_path):
        results = [
            EvalResult(
                pr_id="pr1", title="", repo="r", pr_number=1,
                ground_truth_count=1,
                true_positives=[{"file": "a.py"}],
                false_positives=[],
                false_negatives=[],
            ),
            EvalResult(
                pr_id="pr2", title="", repo="r", pr_number=2,
                ground_truth_count=1,
                true_positives=[],
                false_positives=[{"file": "b.py"}],
                false_negatives=[{"file": "c.py"}],
            ),
        ]
        table = build_results_table(results, tmp_path / "out.md")
        assert "2 PRs evaluated" in table
        assert "0.500" in table

    def test_file_written(self, tmp_path):
        r = EvalResult(pr_id="t", title="t", repo="r", pr_number=1, ground_truth_count=0)
        out = tmp_path / "summary.md"
        build_results_table([r], out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "t" in content


class TestEvaluationHarness:
    def test_stale_err_result_is_re_evaluated(self, tmp_path, monkeypatch):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        err_result = {
            "pr_id": "err-pr", "title": "Err", "repo": "r", "pr_number": 1,
            "ground_truth_count": 1, "true_positives": [], "false_positives": [],
            "false_negatives": [{"file": "a.py", "severity": "high", "description": "x"}],
            "agent_risk_rating": None, "agent_confidence": None,
            "agent_error": "Groq API returned no response",
            "agent_iterations": 1, "agent_reflection_used": False,
            "fetch_error": None, "runtime_seconds": 5.0,
        }
        (results_dir / "err-pr_result.json").write_text(json.dumps(err_result))

        dataset = [{
            "id": "err-pr", "title": "Err", "repo": "r", "pr_number": 1,
            "pr_url": "https://github.com/r/r/pull/1",
            "ground_truth_issues": [{"file": "a.py", "severity": "high", "description": "x"}],
        }]
        from pr_triage_agent.evaluation.run_eval import EvaluationHarness, EvalResult

        evaluated = []
        def fake_evaluate(entry, pr_id):
            evaluated.append(pr_id)
            return EvalResult(
                pr_id=pr_id, title=entry.get("title", ""),
                repo=entry.get("repo", ""), pr_number=entry.get("pr_number", 0),
                ground_truth_count=len(entry.get("ground_truth_issues", [])),
            )

        harness = EvaluationHarness(dataset, results_dir, skip_existing=True)
        monkeypatch.setattr(harness, "_evaluate_single", fake_evaluate)

        harness.run()
        assert "err-pr" in evaluated, "ERR result should trigger re-evaluation, not skip"

    def test_successful_result_is_skipped(self, tmp_path, monkeypatch):
        results_dir = tmp_path / "results2"
        results_dir.mkdir()
        ok_result = {
            "pr_id": "ok-pr", "title": "Ok", "repo": "r", "pr_number": 2,
            "ground_truth_count": 1, "true_positives": [{"file": "a.py"}],
            "false_positives": [], "false_negatives": [],
            "agent_risk_rating": "low", "agent_confidence": 0.8,
            "agent_error": None, "agent_iterations": 3,
            "agent_reflection_used": False, "fetch_error": None,
            "runtime_seconds": 10.0,
        }
        (results_dir / "ok-pr_result.json").write_text(json.dumps(ok_result))

        dataset = [{
            "id": "ok-pr", "title": "Ok", "repo": "r", "pr_number": 2,
            "pr_url": "https://github.com/r/r/pull/2",
            "ground_truth_issues": [{"file": "a.py", "severity": "low", "description": "y"}],
        }]
        from pr_triage_agent.evaluation.run_eval import EvaluationHarness, EvalResult

        evaluated = []
        def fake_evaluate(entry, pr_id):
            evaluated.append(pr_id)
            return EvalResult(
                pr_id=pr_id, title=entry.get("title", ""),
                repo=entry.get("repo", ""), pr_number=entry.get("pr_number", 0),
                ground_truth_count=len(entry.get("ground_truth_issues", [])),
            )

        harness = EvaluationHarness(dataset, results_dir, skip_existing=True)
        monkeypatch.setattr(harness, "_evaluate_single", fake_evaluate)

        harness.run()
        assert "ok-pr" not in evaluated, "Successful result should be skipped"


class TestLoadDataset:
    def test_load_valid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"id": "test-1", "title": "Test"}], f)
            f.flush()
            data = load_dataset(Path(f.name))
            assert len(data) == 1
            assert data[0]["id"] == "test-1"

    def test_missing_file(self):
        with pytest.raises(SystemExit):
            load_dataset(Path("/nonexistent/dataset.json"))
