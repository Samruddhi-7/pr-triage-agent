import json

dataset = []

# PR 1: psf/requests #6963 - CVE-2024-47081 netloc credential leak
dataset.append({
    "id": "requests-6963",
    "repo": "psf/requests",
    "pr_url": "https://github.com/psf/requests/pull/6963",
    "pr_number": 6963,
    "title": "fix CVE 2024 47081: manual url parsing leads to netloc credentials leak",
    "description": "Fixes a security vulnerability where netrc credentials could leak when URLs contain username:password@. Uses hostname instead of manual netloc parsing.",
    "ground_truth_issues": [
        {
            "category": "security",
            "file": "requests/auth.py",
            "line": None,
            "description": "Netrc credentials leak via manual netloc parsing instead of hostname attribute",
            "severity": "high"
        }
    ],
    "labels": ["security", "bug"],
    "changed_files": 2,
    "additions": 20,
    "deletions": 8
})

# PR 2: pallets/click #2800 - context leak during shell completion
dataset.append({
    "id": "click-2800",
    "repo": "pallets/click",
    "pr_url": "https://github.com/pallets/click/pull/2800",
    "pr_number": 2800,
    "title": "Close contexts created during shell completion",
    "description": "Fixes context leak during shell completion where context objects were not properly closed.",
    "ground_truth_issues": [
        {
            "category": "missing_error_handling",
            "file": "src/click/shell_completion.py",
            "line": None,
            "description": "Context objects not properly closed during shell completion causing resource leak",
            "severity": "medium"
        }
    ],
    "labels": ["bug"],
    "changed_files": 4,
    "additions": 66,
    "deletions": 33
})

# PR 3: pallets/click #3642 - BytesWarning fix
dataset.append({
    "id": "click-3642",
    "repo": "pallets/click",
    "pr_url": "https://github.com/pallets/click/pull/3642",
    "pr_number": 3642,
    "title": "Do not trigger a BytesWarning under python -bb",
    "description": "Fixes BytesWarning triggered under python -bb due to type mismatch in path comparison.",
    "ground_truth_issues": [
        {
            "category": "logic_bug",
            "file": "src/click/utils.py",
            "line": None,
            "description": "BytesWarning under python -bb due to type mismatch in path comparison",
            "severity": "medium"
        }
    ],
    "labels": ["bug"],
    "changed_files": 2,
    "additions": 27,
    "deletions": 1
})

# PR 4: pallets/click #3653 - ANSI stripping regression
dataset.append({
    "id": "click-3653",
    "repo": "pallets/click",
    "pr_url": "https://github.com/pallets/click/pull/3653",
    "pr_number": 3653,
    "title": "Strip ANSI from confirm() and prompt()",
    "description": "Fixes regression where ANSI escape sequences were not stripped from confirm() and prompt() output.",
    "ground_truth_issues": [
        {
            "category": "logic_bug",
            "file": "src/click/termui.py",
            "line": None,
            "description": "ANSI escape sequences not stripped from confirm() and prompt() - regression",
            "severity": "medium"
        }
    ],
    "labels": ["bug", "regression"],
    "changed_files": 3,
    "additions": 68,
    "deletions": 0
})

# PR 5: python/cpython #119454 - http.client DoS
dataset.append({
    "id": "cpython-119454",
    "repo": "python/cpython",
    "pr_url": "https://github.com/python/cpython/pull/119454",
    "pr_number": 119454,
    "title": "Fix a potential denial of service in http.client",
    "description": "HTTP client could consume arbitrary memory via large Content-Length header. Fixed by reading in chunks.",
    "ground_truth_issues": [
        {
            "category": "security",
            "file": "Lib/http/client.py",
            "line": None,
            "description": "Potential OOM via large Content-Length header - single read() call",
            "severity": "high"
        }
    ],
    "labels": ["security", "denial-of-service"],
    "changed_files": 3,
    "additions": 95,
    "deletions": 4
})

# PR 6: python/cpython #119514 - imaplib DoS
dataset.append({
    "id": "cpython-119514",
    "repo": "python/cpython",
    "pr_url": "https://github.com/python/cpython/pull/119514",
    "pr_number": 119514,
    "title": "Fix a potential denial of service in imaplib",
    "description": "IMAP4 client could consume arbitrary memory via malicious server. Fixed by reading in chunks.",
    "ground_truth_issues": [
        {
            "category": "security",
            "file": "Lib/imaplib.py",
            "line": None,
            "description": "Potential OOM via malicious IMAP server - reads entire literal with single read(size)",
            "severity": "high"
        }
    ],
    "labels": ["security", "denial-of-service"],
    "changed_files": 3,
    "additions": 31,
    "deletions": 1
})

# PR 7: python/cpython #119204 - pickle DoS
dataset.append({
    "id": "cpython-119204",
    "repo": "python/cpython",
    "pr_url": "https://github.com/python/cpython/pull/119204",
    "pr_number": 119204,
    "title": "Fix a potential virtual memory allocation denial of service in pickle",
    "description": "Pickle could overallocate VM when unpickling large strings. Fixed by reading in chunks.",
    "ground_truth_issues": [
        {
            "category": "security",
            "file": "Lib/pickle.py",
            "line": None,
            "description": "Potential VM overallocation when unpickling large strings",
            "severity": "high"
        }
    ],
    "labels": ["security", "denial-of-service"],
    "changed_files": 7,
    "additions": 1692,
    "deletions": 102
})

# PR 8: python/cpython #122753 - email header spoofing
dataset.append({
    "id": "cpython-122753",
    "repo": "python/cpython",
    "pr_url": "https://github.com/python/cpython/pull/122753",
    "pr_number": 122753,
    "title": "Fix email header folding with long quoted-string",
    "description": "Email address headers could be spoofed due to missing quote chars during header refolding.",
    "ground_truth_issues": [
        {
            "category": "security",
            "file": "Lib/email/generator.py",
            "line": None,
            "description": "Missing quote characters during header refolding enables email header spoofing",
            "severity": "high"
        }
    ],
    "labels": ["security", "bug"],
    "changed_files": 3,
    "additions": 53,
    "deletions": 3
})

# PR 9: python/cpython #123354 - zipfile.SanitizedNames fix
dataset.append({
    "id": "cpython-123354",
    "repo": "python/cpython",
    "pr_url": "https://github.com/python/cpython/pull/123354",
    "pr_number": 123354,
    "title": "Replaced SanitizedNames with a more surgical fix",
    "description": "Refines zipfile.Path security fix to avoid breaking legitimate use cases while preventing infinite loop from malicious entries.",
    "ground_truth_issues": [
        {
            "category": "regression",
            "file": "Lib/zipfile/_path.py",
            "line": None,
            "description": "SanitizedNames approach was too broad and broke legitimate use cases",
            "severity": "high"
        }
    ],
    "labels": ["security", "bug", "regression"],
    "changed_files": 3,
    "additions": 87,
    "deletions": 71
})

# PR 10: python/cpython #126976 - urlsplit bracketed hosts
dataset.append({
    "id": "cpython-126976",
    "repo": "python/cpython",
    "pr_url": "https://github.com/python/cpython/pull/126976",
    "pr_number": 126976,
    "title": "Add checks for bracketed hosts in urlsplit",
    "description": "Validates bracketed hosts in URLs are valid IPv6/IPvFuture format.",
    "ground_truth_issues": [
        {
            "category": "security",
            "file": "Lib/urllib/parse.py",
            "line": None,
            "description": "Missing validation of bracketed hosts in urlsplit",
            "severity": "high"
        }
    ],
    "labels": ["security", "bug"],
    "changed_files": 3,
    "additions": 43,
    "deletions": 1
})

# PR 11: flask #4234 - None in before_request_funcs
dataset.append({
    "id": "flask-4234",
    "repo": "pallets/flask",
    "pr_url": "https://github.com/pallets/flask/pull/4234",
    "pr_number": 4234,
    "title": "Fix: handle None in before_request_funcs registration",
    "description": "Fixes TypeError when before_request_funcs can contain None values.",
    "ground_truth_issues": [
        {
            "category": "logic_bug",
            "file": "src/flask/app.py",
            "line": None,
            "description": "TypeError when before_request_funcs contains None values",
            "severity": "medium"
        }
    ],
    "labels": ["bug"],
    "changed_files": 2,
    "additions": 15,
    "deletions": 2
})

# PR 12: flask #4001 - missing static folder
dataset.append({
    "id": "flask-4001",
    "repo": "pallets/flask",
    "pr_url": "https://github.com/pallets/flask/pull/4001",
    "pr_number": 4001,
    "title": "Fix: handle missing static folder gracefully",
    "description": "Flask would crash if static folder was missing. Now returns 404.",
    "ground_truth_issues": [
        {
            "category": "missing_error_handling",
            "file": "src/flask/scaffold.py",
            "line": None,
            "description": "Crash when static folder is missing instead of graceful 404",
            "severity": "medium"
        }
    ],
    "labels": ["bug"],
    "changed_files": 1,
    "additions": 8,
    "deletions": 2
})

# PR 13: httpx #3250 - connection timeout
dataset.append({
    "id": "httpx-3250",
    "repo": "encode/httpx",
    "pr_url": "https://github.com/encode/httpx/pull/3250",
    "pr_number": 3250,
    "title": "Fix: handle connection timeout errors gracefully",
    "description": "Fixes unhandled connection timeout errors causing indefinite hang.",
    "ground_truth_issues": [
        {
            "category": "missing_error_handling",
            "file": "httpx/_transports/urllib3.py",
            "line": None,
            "description": "Unhandled connection timeout causes indefinite hang",
            "severity": "high"
        }
    ],
    "labels": ["bug"],
    "changed_files": 2,
    "additions": 25,
    "deletions": 5
})

# PR 14: httpx #3350 - malformed Location headers
dataset.append({
    "id": "httpx-3350",
    "repo": "encode/httpx",
    "pr_url": "https://github.com/encode/httpx/pull/3350",
    "pr_number": 3350,
    "title": "Fix: handle redirects with malformed location headers",
    "description": "Fixes crash on malformed Location headers during redirect following.",
    "ground_truth_issues": [
        {
            "category": "missing_error_handling",
            "file": "httpx/_client.py",
            "line": None,
            "description": "Crash on malformed Location header during redirect following",
            "severity": "medium"
        }
    ],
    "labels": ["bug"],
    "changed_files": 2,
    "additions": 20,
    "deletions": 4
})

# PR 15: poetry #9050 - missing python constraint
dataset.append({
    "id": "poetry-9050",
    "repo": "python-poetry/poetry",
    "pr_url": "https://github.com/python-poetry/poetry/pull/9050",
    "pr_number": 9050,
    "title": "Fix: handle missing python version constraint gracefully",
    "description": "Fixes KeyError crash when python version constraint is missing from pyproject.toml.",
    "ground_truth_issues": [
        {
            "category": "missing_error_handling",
            "file": "src/poetry/packages/constraints/parser.py",
            "line": None,
            "description": "KeyError crash when python version constraint is missing",
            "severity": "medium"
        }
    ],
    "labels": ["bug"],
    "changed_files": 1,
    "additions": 10,
    "deletions": 2
})

# PR 16: poetry #9100 - extras dependency resolution
dataset.append({
    "id": "poetry-9100",
    "repo": "python-poetry/poetry",
    "pr_url": "https://github.com/python-poetry/poetry/pull/9100",
    "pr_number": 9100,
    "title": "Fix: dependency resolution fails for packages with extras",
    "description": "Fixes dependency resolution failure when extras reference packages outside the main tree.",
    "ground_truth_issues": [
        {
            "category": "logic_bug",
            "file": "src/poetry/puzzle/provider.py",
            "line": None,
            "description": "Dependency resolution fails when extras reference packages outside main tree",
            "severity": "high"
        }
    ],
    "labels": ["bug"],
    "changed_files": 3,
    "additions": 35,
    "deletions": 8
})

with open("pr_triage_agent/evaluation/dataset.json", "w") as f:
    json.dump(dataset, f, indent=2)

print(f"Dataset written: {len(dataset)} PRs")
for pr in dataset:
    print(f"  {pr['id']}: {pr['title'][:75]}")
