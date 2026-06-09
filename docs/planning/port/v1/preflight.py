"""
preflight.py — Pre-flight environment checks for orchestrator startup.

Validates that the orchestrator has all required dependencies and permissions
before beginning work. Checks include:
  - claude CLI is present and runnable
  - git user.name and user.email are configured
  - policy file (self_dev_policy.json) parses cleanly
  - working tree is clean (no uncommitted changes)
  - state/ directory is writable
  - disk free space >= 1 GB
  - weekly quota window is calculable

Usage:
    import preflight
    issues = preflight.check()
    if issues:
        for issue in issues:
            print(f"  {issue['severity']}: {issue['message']}")

Returns a list of dicts with keys:
  - message: human-readable description of the issue
  - severity: 'critical' or 'warning'
  - check: the name of the check that found this issue
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

# On Windows, npm-installed CLIs (claude, git from Git for Windows) are .cmd
# batch files that subprocess can only find when shell=True is set.
_USE_SHELL = sys.platform == "win32"

# ── Constants ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
POLICY_FILE = ROOT / "self_dev_policy.json"
JOURNAL_DIR = ROOT / "journal"
PREFLIGHT_LOG = JOURNAL_DIR / "preflight.log"

# Severity levels: critical blocks startup, warning allows startup with caution
CRITICAL = "critical"
WARNING = "warning"

# Minimum disk free space (1 GB in bytes)
MIN_DISK_FREE_BYTES = 1024 * 1024 * 1024


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class PreflightIssue:
    """Represents one preflight check issue."""
    message: str
    severity: str  # "critical" or "warning"
    check: str     # Name of the check that found this issue

    def to_dict(self) -> Dict[str, str]:
        """Convert to dict for JSON serialization."""
        return {
            "message": self.message,
            "severity": self.severity,
            "check": self.check,
        }


# ── Check functions ───────────────────────────────────────────────────────────

def _augmented_env() -> dict:
    """Return an env overlay that ensures claude.cmd is findable on Windows.

    Mirrors _claude_path_env() in agents/common.py; duplicated here so
    preflight has no import dependency on agents/.
    """
    if sys.platform != 'win32':
        return {}
    if shutil.which('claude'):
        return {}
    import os as _os
    appdata    = _os.environ.get('APPDATA', '')
    userprofile = _os.environ.get('USERPROFILE', '')
    nvm_home   = _os.environ.get('NVM_HOME', '')
    candidates = [
        _os.path.join(appdata, 'npm'),
        _os.path.join(userprofile, 'AppData', 'Roaming', 'npm'),
        r'C:\Program Files\nodejs',
    ]
    if nvm_home:
        candidates.append(nvm_home)
    nvm_root = _os.path.join(appdata, 'nvm')
    if _os.path.isdir(nvm_root):
        try:
            for entry in sorted(_os.listdir(nvm_root), reverse=True):
                candidates.append(_os.path.join(nvm_root, entry))
        except OSError:
            pass
    for d in candidates:
        if _os.path.isfile(_os.path.join(d, 'claude.cmd')):
            return {'PATH': d + _os.pathsep + _os.environ.get('PATH', '')}
    return {}


def _check_claude_cli() -> Optional[PreflightIssue]:
    """Check that claude CLI is present and runnable."""
    _env = {**__import__('os').environ, **_augmented_env()} or None
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            timeout=5,
            text=True,
            shell=_USE_SHELL,
            env=_env,
        )
        if result.returncode != 0:
            return PreflightIssue(
                message="claude CLI is installed but --version returned non-zero exit code",
                severity=CRITICAL,
                check="claude_cli",
            )
        return None
    except FileNotFoundError:
        return PreflightIssue(
            message="claude CLI not found in PATH",
            severity=CRITICAL,
            check="claude_cli",
        )
    except subprocess.TimeoutExpired:
        return PreflightIssue(
            message="claude CLI exists but did not respond to --version within 5 seconds",
            severity=CRITICAL,
            check="claude_cli",
        )
    except Exception as exc:
        return PreflightIssue(
            message=f"Error checking claude CLI: {exc}",
            severity=CRITICAL,
            check="claude_cli",
        )


def _check_git_config() -> List[PreflightIssue]:
    """Check that git user.name and user.email are configured."""
    issues = []

    # Check user.name
    try:
        result = subprocess.run(
            ["git", "config", "--get", "user.name"],
            capture_output=True,
            timeout=5,
            text=True,
            cwd=str(ROOT),
            shell=_USE_SHELL,
        )
        if result.returncode != 0 or not result.stdout.strip():
            issues.append(PreflightIssue(
                message="git user.name is not configured (run: git config --global user.name 'Your Name')",
                severity=CRITICAL,
                check="git_config",
            ))
    except Exception as exc:
        issues.append(PreflightIssue(
            message=f"Error checking git user.name: {exc}",
            severity=CRITICAL,
            check="git_config",
        ))

    # Check user.email
    try:
        result = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True,
            timeout=5,
            text=True,
            cwd=str(ROOT),
            shell=_USE_SHELL,
        )
        if result.returncode != 0 or not result.stdout.strip():
            issues.append(PreflightIssue(
                message="git user.email is not configured (run: git config --global user.email 'your@email.com')",
                severity=CRITICAL,
                check="git_config",
            ))
    except Exception as exc:
        issues.append(PreflightIssue(
            message=f"Error checking git user.email: {exc}",
            severity=CRITICAL,
            check="git_config",
        ))

    return issues


def _check_policy_file() -> Optional[PreflightIssue]:
    """Check that policy file exists and parses cleanly."""
    if not POLICY_FILE.exists():
        return PreflightIssue(
            message=f"Policy file not found: {POLICY_FILE}",
            severity=CRITICAL,
            check="policy_file",
        )

    try:
        raw = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        # Basic structure validation
        if not isinstance(raw, dict):
            return PreflightIssue(
                message="Policy file is not a JSON object",
                severity=CRITICAL,
                check="policy_file",
            )
        # Check required top-level keys (not strictly required, but expected)
        # Allow graceful degradation if keys are missing
        return None
    except json.JSONDecodeError as exc:
        return PreflightIssue(
            message=f"Policy file is not valid JSON: {exc}",
            severity=CRITICAL,
            check="policy_file",
        )
    except Exception as exc:
        return PreflightIssue(
            message=f"Error reading policy file: {exc}",
            severity=CRITICAL,
            check="policy_file",
        )


def _check_working_tree_clean() -> Optional[PreflightIssue]:
    """Check that git working tree is clean (no uncommitted changes).

    Disabled: agent outputs (context/graph.json, etc.) legitimately leave the
    tree dirty between runs. The developer agent no longer blocks on a dirty
    tree, so this check produces only noise.
    """
    return None

def _check_state_dir_writable() -> Optional[PreflightIssue]:
    """Check that state/ directory exists and is writable."""
    # Create state/ if it doesn't exist
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return PreflightIssue(
            message=f"Cannot create state/ directory: {exc}",
            severity=CRITICAL,
            check="state_dir_writable",
        )

    # Test write permission by creating a temporary file
    try:
        with tempfile.NamedTemporaryFile(dir=str(STATE_DIR), delete=True):
            pass
        return None
    except Exception as exc:
        return PreflightIssue(
            message=f"state/ directory is not writable: {exc}",
            severity=CRITICAL,
            check="state_dir_writable",
        )


def _check_disk_free() -> Optional[PreflightIssue]:
    """Check that disk has at least 1 GB free."""
    try:
        # shutil.disk_usage works on all platforms (unlike os.statvfs which is Unix-only)
        usage = shutil.disk_usage(str(ROOT))
        free_bytes = usage.free
        if free_bytes < MIN_DISK_FREE_BYTES:
            free_gb = free_bytes / (1024 * 1024 * 1024)
            return PreflightIssue(
                message=f"Disk free space is {free_gb:.2f} GB; minimum 1 GB required",
                severity=WARNING,
                check="disk_free",
            )
        return None
    except Exception as exc:
        return PreflightIssue(
            message=f"Error checking disk space: {exc}",
            severity=WARNING,
            check="disk_free",
        )


def _check_quota_window() -> Optional[PreflightIssue]:
    """Check that weekly quota window is calculable.

    The quota window is based on the current UTC week number. This check
    ensures that the datetime module can calculate it without errors.
    """
    try:
        now = datetime.now(timezone.utc)
        # Calculate the Monday of this week (week starts on Monday, ISO 8601)
        days_since_monday = now.weekday()
        week_start = now - timedelta(days=days_since_monday)
        # Verify we can do basic date arithmetic without errors
        _ = week_start.isoformat()
        return None
    except Exception as exc:
        return PreflightIssue(
            message=f"Error calculating quota window: {exc}",
            severity=WARNING,
            check="quota_window",
        )


def _check_python_dependencies() -> Optional[PreflightIssue]:
    """Check that required Python packages are installed.

    The orchestrator requires:
      - flask >= 3.0.0 (HTTP API server for dashboard)

    Note: the anthropic SDK is no longer required; the validator and all
    agents now invoke the Claude CLI directly via subprocess.

    Users can install these with: pip install -r requirements.txt
    """
    missing = []
    try:
        import flask  # noqa: F401
    except ImportError:
        missing.append("flask")

    if missing:
        modules_str = ", ".join(missing)
        return PreflightIssue(
            message=f"Required Python packages not installed: {modules_str}. Install with: pip install -r requirements.txt",
            severity=CRITICAL,
            check="python_dependencies",
        )
    return None


# ── Main check function ────────────────────────────────────────────────────────

def check() -> List[PreflightIssue]:
    """
    Run all preflight checks and return a list of issues found.

    Returns:
        List[PreflightIssue] — list of all issues (critical and warning).
        Empty list means all checks passed.
    """
    issues: List[PreflightIssue] = []

    # Run each check function
    issue = _check_claude_cli()
    if issue:
        issues.append(issue)

    issue = _check_python_dependencies()
    if issue:
        issues.append(issue)

    issues.extend(_check_git_config())

    issue = _check_policy_file()
    if issue:
        issues.append(issue)

    issue = _check_working_tree_clean()
    if issue:
        issues.append(issue)

    issue = _check_state_dir_writable()
    if issue:
        issues.append(issue)

    issue = _check_disk_free()
    if issue:
        issues.append(issue)

    issue = _check_quota_window()
    if issue:
        issues.append(issue)

    return issues


def has_critical_issues(issues: List[PreflightIssue]) -> bool:
    """Check if any issues are critical (block startup)."""
    return any(issue.severity == CRITICAL for issue in issues)


def write_issues_to_log(issues: List[PreflightIssue]) -> None:
    """Write preflight issues to journal/preflight.log.

    Creates the journal directory if needed. Appends issues to the log file
    in JSON Lines format (one JSON object per line).
    """
    try:
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        with open(PREFLIGHT_LOG, "a", encoding="utf-8") as f:
            for issue in issues:
                f.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "issue": issue.to_dict(),
                }) + "\n")
    except Exception as exc:
        logging.error("Error writing preflight log: %s", exc)


def format_issues_for_display(issues: List[PreflightIssue]) -> str:
    """Format issues as a multi-line string suitable for display or logging."""
    if not issues:
        return "No issues found"

    lines = [f"Found {len(issues)} preflight issue(s):"]
    critical = [i for i in issues if i.severity == CRITICAL]
    warnings = [i for i in issues if i.severity == WARNING]

    if critical:
        lines.append(f"\n  CRITICAL ({len(critical)}):")
        for issue in critical:
            lines.append(f"    - {issue.message}")

    if warnings:
        lines.append(f"\n  WARNING ({len(warnings)}):")
        for issue in warnings:
            lines.append(f"    - {issue.message}")

    return "\n".join(lines)


if __name__ == "__main__":
    """Allow running as a standalone script: python3 preflight.py"""
    issues = check()
    print(format_issues_for_display(issues))
    if has_critical_issues(issues):
        print("\n❌ Critical issues found; orchestrator cannot boot.")
        exit(1)
    elif issues:
        print("\n⚠️ Warnings found; orchestrator will proceed but check these.")
        exit(0)
    else:
        print("\n✅ All preflight checks passed.")
        exit(0)
