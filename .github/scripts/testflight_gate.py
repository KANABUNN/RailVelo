"""Fail-closed GitHub-only prerequisite gate; no Apple credentials are used here."""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "KANABUNN/RailVelo"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


class GateError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GateError("redirect_rejected")


def read_json(url, token):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise GateError("github_host_rejected")
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "RailVelo-TestFlight-Gate",
    })
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError, OSError) as error:
        raise GateError("github_request_failed") from error


def validate_context(repository, ref, event, source_sha):
    if repository != REPOSITORY or ref != "refs/heads/main" or event != "workflow_dispatch":
        raise GateError("dispatch_context_rejected")
    if not SHA_PATTERN.fullmatch(source_sha):
        raise GateError("full_source_sha_required")
    return source_sha


def validate_comparison(comparison, source_sha, main_sha):
    if comparison.get("status") not in ("ahead", "identical"):
        raise GateError("source_not_main_ancestor")
    if comparison.get("merge_base_commit", {}).get("sha") != source_sha:
        raise GateError("source_not_main_ancestor")
    if comparison.get("base_commit", {}).get("sha") != source_sha:
        raise GateError("comparison_base_mismatch")
    if not SHA_PATTERN.fullmatch(main_sha):
        raise GateError("invalid_main_sha")


def qualifying_run(run, workflow_id, source_sha):
    return (
        run.get("workflow_id") == workflow_id
        and run.get("head_sha") == source_sha
        and run.get("head_branch") == "main"
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("event") in ("push", "workflow_dispatch")
        and run.get("status") == "completed" and run.get("conclusion") == "success"
        and isinstance(run.get("id"), int) and not isinstance(run.get("id"), bool)
        and run["id"] > 0
    )


def gate(source_sha, token, get=read_json):
    base = "https://api.github.com/repos/" + REPOSITORY
    main_sha = get(base + "/commits/main", token).get("sha", "")
    if not SHA_PATTERN.fullmatch(main_sha):
        raise GateError("invalid_main_sha")
    comparison = get(base + "/compare/" + source_sha + "..." + main_sha, token)
    validate_comparison(comparison, source_sha, main_sha)
    evidence = {"repository": REPOSITORY, "source_sha": source_sha, "main_sha": main_sha}
    for filename, label in (("swift.yml", "engine_run_id"), ("ios.yml", "app_run_id")):
        workflow = get(base + "/actions/workflows/" + filename, token)
        workflow_id = workflow.get("id")
        if type(workflow_id) is not int or workflow.get("path") != ".github/workflows/" + filename:
            raise GateError("workflow_identity_mismatch")
        accepted = None
        for page in range(1, 11):
            query = urllib.parse.urlencode({"head_sha": source_sha, "per_page": 100, "page": page})
            document = get(base + "/actions/workflows/" + str(workflow_id) + "/runs?" + query, token)
            runs = document.get("workflow_runs")
            if not isinstance(runs, list):
                raise GateError("workflow_response_invalid")
            candidates = [r["id"] for r in runs if qualifying_run(r, workflow_id, source_sha)]
            if candidates:
                accepted = max(candidates)
                break
            if len(runs) < 100:
                break
        if accepted is None:
            raise GateError("same_sha_success_required_" + label)
        evidence[label] = accepted
    return evidence


def main():
    try:
        sha = validate_context(os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_REF"),
                               os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("SOURCE_SHA", ""))
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            raise GateError("github_token_missing")
        evidence = gate(sha, token)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            for key, value in evidence.items():
                output.write(f"{key}={value}\n")
        print("Exact source SHA has successful engine and app runs and is on main history.")
    except GateError as error:
        print("TestFlight prerequisite rejected: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("TestFlight prerequisite rejected: unexpected_error", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
