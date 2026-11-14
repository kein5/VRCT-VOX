"""Writes CHANGELOG.md when a release is prepared, and the GitHub release notes from it.

    python tools/changelog.py write           # add the section of package.json's version
    python tools/changelog.py print           # show that section, write nothing
    python tools/changelog.py check           # fail unless CHANGELOG.md has that section
    python tools/changelog.py release-notes --output notes.md

Cocogitto reads the commits (`cog changelog <previous tag>..HEAD` with
tools/changelog_commits.tera); this file sorts them for readers. A section covers the commits
since the nearest earlier release tag (v*). It is written once per release: running it again
gives the same file, and a section that would come out differently is not replaced unless
--force is given. The rules are in CONTRIBUTING.md, "Changelog and releases".
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/kein5/VRCT-VOX"
TEMPLATE = Path(__file__).resolve().with_name("changelog_commits.tera")
TEMPLATE_CHECKLIST = ROOT / "docs" / "release-draft-template.md"

USER, INTERNAL = "user", "internal"
USER_HEADINGS = ("Breaking Changes", "Features", "Improvements", "Bug Fixes", "Performance", "Security")
INTERNAL_HEADINGS = ("Refactoring", "Dependencies", "Build & CI", "Tests", "Documentation", "Maintenance")
GROUP_TITLES = {USER: "User-facing Changes", INTERNAL: "Internal Changes"}
# A feat, fix or perf in these scopes changes how VRCT-VOX is built or checked, not the app.
DEVELOPER_SCOPES = {"dev": "Maintenance", "tooling": "Maintenance", "ci": "Build & CI", "build": "Build & CI",
                    "test": "Tests", "tests": "Tests", "deps": "Dependencies", "docs": "Documentation"}
INTERNAL_BY_TYPE = {"refactor": "Refactoring", "build": "Build & CI", "ci": "Build & CI", "test": "Tests",
                    "docs": "Documentation", "chore": "Maintenance", "style": "Maintenance", "revert": "Maintenance",
                    "feat": "Maintenance", "fix": "Maintenance", "perf": "Maintenance"}
USER_BY_TYPE = {"feat": "Features", "fix": "Bug Fixes", "perf": "Performance"}
CHANGELOG_FOOTER = "changelog"
FOOTER_VALUES = {"user", "security", "internal", "skip"}
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")
SECTION = re.compile(r"^## \[(?P<version>[^\]]+)\] - (?P<date>\d{4}-\d{2}-\d{2})$", re.M)
OLDER_HEADING = "## Earlier releases"
HEADER = """# Changelog

All notable changes to VRCT-VOX, newest first. Versions follow [Semantic Versioning](https://semver.org/);
`X.Y.Z-beta.N` versions are pre-releases from `develop`. The layout follows the ideas of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/): changes that users notice come first, and
changes for developers follow.

A section is written when its release is prepared (`python tools/changelog.py write`), not on
every commit. See [Changelog and releases](CONTRIBUTING.md#changelog-and-releases).
"""
OLDER = f"""{OLDER_HEADING}

Releases up to 0.1.0 are described in [GitHub Releases]({REPO_URL}/releases).
"""


class ChangelogError(Exception):
    pass


@dataclass(frozen=True)
class Commit:
    id: str
    type: str
    scope: str | None
    summary: str
    breaking: bool
    footers: tuple = ()

    def footer(self, token):
        return next((content.strip() for name, content in self.footers if name.lower() == token), None)


def load_type_titles(path=ROOT / "cog.toml"):
    """Maps each changelog title in cog.toml back to its commit type."""
    types = tomllib.loads(Path(path).read_text(encoding="utf-8"))["commit_types"]
    titles = {config["changelog_title"]: name for name, config in types.items()}
    if len(titles) != len(types):
        raise ChangelogError("cog.toml: two commit types share a changelog_title")
    return titles


def parse_commits(lines, titles):
    commits = []
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        if row["type"] not in titles:
            raise ChangelogError(f"commit {row['id'][:7]}: type '{row['type']}' is not in cog.toml")
        footers = tuple((item["footer"]["token"], item["footer"]["content"])
                        for item in row.get("footers") or [] if "footer" in item)
        commits.append(Commit(id=row["id"], type=titles[row["type"]], scope=row.get("scope"), summary=row["summary"],
                              breaking=bool(row.get("breaking_change")), footers=footers))
    return commits


def classify(commit):
    """Returns (group, heading), or None for a commit left out."""
    choice = (commit.footer(CHANGELOG_FOOTER) or "").lower()
    if choice and choice not in FOOTER_VALUES:
        raise ChangelogError(f"commit {commit.id[:7]}: 'Changelog: {choice}' is not one of {sorted(FOOTER_VALUES)}")
    if choice == "skip" or (commit.type == "chore" and commit.scope == "release"):
        return None
    if choice == "internal":
        return INTERNAL, internal_heading(commit)
    if commit.breaking:
        return USER, "Breaking Changes"
    if choice == "security" or (commit.scope == "security" and commit.type in USER_BY_TYPE):
        return USER, "Security"
    if choice == "user":
        return USER, USER_BY_TYPE.get(commit.type, "Improvements")
    if commit.type in USER_BY_TYPE and commit.scope not in DEVELOPER_SCOPES:
        return USER, USER_BY_TYPE[commit.type]
    return INTERNAL, internal_heading(commit)


def internal_heading(commit):
    if commit.scope == "deps":
        return "Dependencies"
    if commit.type in USER_BY_TYPE and commit.scope in DEVELOPER_SCOPES:
        return DEVELOPER_SCOPES[commit.scope]
    return INTERNAL_BY_TYPE[commit.type]


def render_section(version, date, previous_tag, commits, *, repo_url=REPO_URL, included=()):
    lines = [f"## [{version}] - {date}", ""]
    if previous_tag:
        lines += [f"Changes since [{previous_tag}]({repo_url}/compare/{previous_tag}...v{version}).", ""]
    if included:
        names = included[0] if len(included) == 1 else ", ".join(included[:-1]) + " and " + included[-1]
        lines += [f"This release includes the changes of {names}, listed below.", ""]
    entries = {}  # (group, heading) -> {line key -> entry}
    for commit in commits:
        place = classify(commit)
        if place is None:
            continue
        key = (commit.scope, commit.summary.strip().lower(), breaking_note(commit))
        entry = entries.setdefault(place, {}).setdefault(key, {"commit": commit, "ids": []})
        if commit.id not in entry["ids"]:
            entry["ids"].append(commit.id)
    if not entries:
        lines += ["No changes to list.", ""]
    for group, headings in ((USER, USER_HEADINGS), (INTERNAL, INTERNAL_HEADINGS)):
        present = [heading for heading in headings if (group, heading) in entries]
        if not present:
            continue
        lines += [f"### {GROUP_TITLES[group]}", ""]
        for heading in present:
            lines += [f"#### {heading}", ""]
            for entry in entries[(group, heading)].values():
                lines += entry_lines(entry["commit"], entry["ids"], repo_url)
            lines.append("")
    return "\n".join(lines)


def breaking_note(commit):
    return commit.footer("breaking change") or commit.footer("breaking-change") if commit.breaking else None


def entry_lines(commit, ids, repo_url):
    summary = commit.summary.strip()
    summary = summary[:1].upper() + summary[1:]
    scope = f"**{commit.scope}:** " if commit.scope else ""
    links = ", ".join(f"[{sha[:7]}]({repo_url}/commit/{sha})" for sha in ids)
    lines = [f"- {scope}{summary} ({links})"]
    note = breaking_note(commit)
    if note:
        lines.append(f"  - {note}")
    return lines


def sections(text):
    """(version, start, end) of each release section, in file order."""
    found = list(SECTION.finditer(text))
    ends = [match.start() for match in found[1:]]
    older = text.find(OLDER_HEADING)
    result = []
    for match, end in zip(found, ends + [None]):
        if end is None:
            end = older if older > match.start() else len(text)
        result.append((match["version"], match.start(), end))
    return result


def update_changelog(text, version, section, force=False):
    if not text.strip():
        text = HEADER + "\n" + OLDER
    section = section.rstrip("\n") + "\n\n"
    for name, start, end in sections(text):
        if name == version:
            if text[start:end] == section:
                return text
            if not force:
                raise ChangelogError(f"CHANGELOG.md already has a different section for {version}; "
                                     "check it, then run again with --force to replace it")
            return text[:start] + section + text[end:]
    existing = sections(text)
    at = existing[0][1] if existing else text.find(OLDER_HEADING)
    if at < 0:
        at = len(text)
    return text[:at] + section + text[at:]


def section_date(text, version):
    return next((match["date"] for match in SECTION.finditer(text) if match["version"] == version), None)


def section_text(text, version):
    for name, start, end in sections(text):
        if name == version:
            return text[start:end].rstrip("\n")
    raise ChangelogError(f"CHANGELOG.md has no section for {version}; run python tools/changelog.py write first")


def pre_releases(text, version):
    """Pre-releases of a stable version already in the file, oldest first."""
    if "-" in version:
        return []
    found = [name for name, _, _ in sections(text) if name.split("-", 1)[0] == version and "-" in name]
    return sorted(found, key=lambda name: [int(part) if part.isdigit() else part for part in re.split(r"[.-]", name)])


def release_notes(text, version, *, repo_url=REPO_URL, checklist=""):
    """GitHub release notes: what users weigh first, then the user-facing list, internals counted."""
    body = section_text(text, version)
    user = _between(body, "### User-facing Changes", "### Internal Changes")
    internal = _between(body, "### Internal Changes", None)
    breaking = _between(user, "#### Breaking Changes", "#### ") if user else ""
    rest = re.sub(r"#### Breaking Changes\n.*?(?=#### |\Z)", "", user, flags=re.S).strip() if user else ""
    counts = [(heading, len(re.findall(r"^- ", part, re.M)))
              for heading, part in re.findall(r"^#### ([^\n]+)\n(.*?)(?=^#### |\Z)", internal, re.M | re.S)]
    lines = []
    if checklist.strip():
        lines += ["<!--", checklist.strip(), "-->", ""]
    lines += ["## Highlights", "", "_Write two to four lines on what this release gives users before publishing._", "",
              "## Breaking Changes", "", breaking.strip() or "None.", "",
              "## Upgrade Notes", "", "_Write what users must do when they update, or remove this heading._", "",
              "## Known Issues", "", "_List the limitations and the checks that were not run (docs/voice-stack/release-candidates.md)._", "",
              "## Changes", ""]
    lines += [rest.replace("#### ", "### ") or "No user-facing changes.", ""]
    if counts:
        total = sum(count for _, count in counts)
        detail = ", ".join(f"{heading} {count}" for heading, count in counts)
        lines += [f"Internal changes: {total} ({detail}).", ""]
    lines += [f"The full list is in [CHANGELOG.md]({repo_url}/blob/v{version}/CHANGELOG.md).", ""]
    return "\n".join(lines)


def _between(text, start, stop):
    at = text.find(start)
    if at < 0:
        return ""
    at += len(start)
    end = text.find(stop, at) if stop else -1
    return text[at:end if end >= 0 else len(text)].strip("\n")


def require_version(version):
    if not VERSION.fullmatch(version):
        raise ChangelogError(f"'{version}' is not a version like 0.2.0 or 0.2.0-beta.1")


def cog_command():
    if shutil.which("cog"):
        return ["cog"]
    if shutil.which("mise"):
        return ["mise", "exec", "--", "cog"]
    return None


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() if result.returncode == 0 else None


def previous_tag(root, version):
    return git(root, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "--exclude", f"v{version}", "HEAD")


def read_commits(root, since):
    command = cog_command()
    if command is None:
        raise ChangelogError("Cocogitto (cog) is not installed; see docs/development.md")
    result = subprocess.run([*command, "changelog", f"{since}..HEAD", "-t", str(TEMPLATE)], cwd=root,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise ChangelogError(f"cog changelog failed:\n{result.stderr.strip()}")
    return parse_commits(result.stdout.splitlines(), load_type_titles(Path(root) / "cog.toml"))


def build_section(root, version, text, date=None):
    require_version(version)
    if git(root, "rev-parse", "-q", "--verify", f"refs/tags/v{version}"):
        raise ChangelogError(f"the tag v{version} already exists; set the next version in package.json first")
    since = previous_tag(root, version)
    if not since:
        raise ChangelogError("no earlier release tag (v*) is reachable from HEAD")
    date = section_date(text, version) or date or datetime.date.today().isoformat()
    return render_section(version, date, since, read_commits(root, since), included=pre_releases(text, version))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("write", "print", "check", "release-notes"))
    parser.add_argument("--version", help="defaults to package.json's version")
    parser.add_argument("--date", help="the date of a new section (YYYY-MM-DD); defaults to today")
    parser.add_argument("--force", action="store_true", help="replace a section that would come out differently")
    parser.add_argument("--output", help="release-notes: the file to write")
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = Path(args.root)
    version = args.version or json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        if args.command == "check":
            section_text(text, version)
            print(f"CHANGELOG.md has a section for {version}")
        elif args.command == "release-notes":
            checklist = TEMPLATE_CHECKLIST.read_text(encoding="utf-8") if TEMPLATE_CHECKLIST.exists() else ""
            notes = release_notes(text, version, checklist=checklist)
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(notes, encoding="utf-8", newline="\n")
            else:
                sys.stdout.write(notes)
        else:
            section = build_section(root, version, text, args.date)
            if args.command == "print":
                sys.stdout.write(section)
                return 0
            updated = update_changelog(text, version, section, force=args.force)
            if updated == text:
                print(f"CHANGELOG.md already has this section for {version}; nothing changed")
            else:
                path.write_text(updated, encoding="utf-8", newline="\n")
                print(f"wrote the section for {version} to CHANGELOG.md")
    except ChangelogError as error:
        print(f"changelog: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
