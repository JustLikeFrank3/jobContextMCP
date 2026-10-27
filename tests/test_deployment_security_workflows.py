"""Static release-workflow invariants that are easy to weaken accidentally."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_manual_dispatch_cannot_deploy_outside_protected_branches():
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in deploy
    assert "if: github.ref == 'refs/heads/main'" in deploy
    assert "if: github.ref == 'refs/heads/qa'" in deploy


def test_release_jobs_require_all_branch_specific_security_gates():
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    assert "needs: [test, sast, dast, sonar, dependency-review]" in deploy
    assert "needs: [test, sast, dast, dependency-review]" in deploy
    assert "if: github.ref == 'refs/heads/main'" in deploy
    assert "if: github.ref == 'refs/heads/qa'" in deploy
    assert "uses: ./.github/workflows/dependency-review.yml" in deploy


def test_dependency_review_has_explicit_ranges_for_all_supported_events():
    review = (WORKFLOWS / "dependency-review.yml").read_text(encoding="utf-8")

    for event in ("pull_request", "workflow_call", "workflow_dispatch"):
        assert f"  {event}:" in review
    for event in ("pull_request", "push", "workflow_dispatch"):
        assert f"            {event})" in review
    assert '"Unable to resolve dependency review range; refusing to skip SCA."' in review
    assert "base-ref: ${{ needs.resolve-range.outputs.base-ref }}" in review
    assert "head-ref: ${{ needs.resolve-range.outputs.head-ref }}" in review


def test_deployments_use_digest_from_the_same_build_step():
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    manifests = (
        (ROOT / "k8s" / "deployment.yaml").read_text(encoding="utf-8"),
        (ROOT / "k8s" / "qa" / "deployment.yaml").read_text(encoding="utf-8"),
    )

    assert deploy.count("id: build") == 2
    assert deploy.count("ref: ${{ github.sha }}") == 2
    assert deploy.count("${{ steps.build.outputs.digest }}") == 2
    assert deploy.count("@sha256:[a-f0-9]{64}") == 2
    assert deploy.count('sed "s|__IMAGE_REF__|${IMAGE_REF}|g"') == 2
    assert all("image: __IMAGE_REF__" in manifest for manifest in manifests)
    assert all("<IMAGE_TAG>" not in manifest for manifest in manifests)
    assert "s|<IMAGE_TAG>|${{ github.sha }}|g" not in deploy
    assert "s|<IMAGE_TAG>|qa-${{ github.sha }}|g" not in deploy


def test_deploy_digest_guard_is_strict_sha256():
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    patterns = re.findall(r"\[\[ \"\$IMAGE_REF\" =~ (.*?) \]\]", deploy)
    assert patterns == ["@sha256:[a-f0-9]{64}$", "@sha256:[a-f0-9]{64}$"]