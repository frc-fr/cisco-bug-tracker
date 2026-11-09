"""Cisco release strings, one format per operating system.

Every release is read as a branch, a maintenance number and an optional rebuild:

- IOS          15.9(3)M13, 15.9(3)M0a, 15.2(7)E10  branch 15.9(3)M, maintenance 13, rebuild a
- IOS XE       17.12.3a, 26.1.2                    branch 17.12,    maintenance 3,  rebuild a
- IOS XR       24.4.1, 7.11.21                     branch 24.4,     maintenance 1;  7.11.21 rebuilds 7.11.2
- NX-OS        10.5(5)M, 9.3(16), 10.3(4a)M        branch 10.5,     maintenance 5,  rebuild a
- ASA          9.22(1.1), 9.20(3)                  branch 9.22,     maintenance 1,  interim 1
- FTD          7.6.1, 7.4.2.1                      branch 7.6,      maintenance 1,  patch 1

A maintenance release carries the fixes of the earlier maintenance releases of its
branch. A rebuild only follows its own maintenance release: a fix in 17.12.3a is in
17.12.3b, and nothing says it is in 17.12.4.
"""
import re
from typing import Dict, List, Optional, Tuple

SYSTEMS: Dict[str, str] = {
    "iosxe": "IOS XE",
    "ios": "IOS",
    "iosxr": "IOS XR",
    "nxos": "NX-OS",
    "asa": "ASA",
    "ftd": "FTD",
}

# How each system writes a release in running text: anchored on word limits.
PATTERNS = {
    "ios": r"1[25]\.\d\(\d+\)[A-Z]{1,3}\d*[a-wyz]?",
    "iosxe": r"(?:1[67]|2[6-9])\.\d{1,2}\.\d{1,2}[a-z]?",
    "iosxr": r"(?:[67]|2[4-9])\.\d{1,2}\.\d{1,2}",
    "nxos": r"(?:[89]|10)\.\d\(\d+[a-z]?\)[A-Z]?",
    "asa": r"9\.\d{1,2}\(\d+(?:\.\d+)?\)",
    "ftd": r"[67]\.\d{1,2}\.\d{1,2}(?:\.\d{1,2})?|10\.\d\.\d{1,2}(?:\.\d{1,2})?",
}
FINDERS = {system: re.compile(rf"(?<![\w.(])({pattern})(?![\w(]|\.\d)") for system, pattern in PATTERNS.items()}
# A whole branch, as notes covering several releases name it: "17.12.x", "9.22(x)", "Version 7.6.x".
BRANCHES = {
    "ios": re.compile(r"(?<![\w.])(1[25]\.\d\(\d+\)[A-Z]{1,3})x?(?![\w(])"),
    "iosxe": re.compile(r"(?<![\w.])((?:1[67]|2[6-9])\.\d{1,2})\.x\b", re.I),
    "iosxr": re.compile(r"(?<![\w.])((?:[67]|2[4-9])\.\d{1,2})\.x\b", re.I),
    "nxos": re.compile(r"(?<![\w.])((?:[89]|10)\.\d)(?:\(x\)|\.x)(?![\w(.])", re.I),
    "asa": re.compile(r"(?<![\w.])(9\.\d{1,2})\(x\)", re.I),
    "ftd": re.compile(r"(?<![\w.])([67]\.\d{1,2}|10\.\d)\.x\b", re.I),
}

PARTS = {
    "ios": re.compile(r"^(1[25])\.(\d)\((\d+)\)([A-Z]{1,3})(\d*)([a-wyz]?)$"),
    "iosxe": re.compile(r"^(\d+)\.(\d+)\.(\d+)([a-z]?)$"),
    "iosxr": re.compile(r"^(\d+)\.(\d+)\.(\d+)$"),
    "nxos": re.compile(r"^(\d+)\.(\d+)\((\d+)([a-z]?)\)([A-Z]?)$"),
    "asa": re.compile(r"^(\d+)\.(\d+)\((\d+)(?:\.(\d+))?\)$"),
    "ftd": re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$"),
}

# Older releases are out of scope: their notes use other layouts and their branches ended long ago.
FLOORS = {"ios": (15, 0), "iosxe": (16, 9), "iosxr": (7, 0), "nxos": (8, 4), "asa": (9, 12), "ftd": (6, 4)}


def parts(system: str, version: str) -> Tuple[str, int, str]:
    """(branch, maintenance, rebuild) of a release; rebuild is "" for a maintenance release."""
    match = PARTS[system].match(version)
    if not match:
        raise ValueError(f"not a {SYSTEMS[system]} release: {version!r}")
    g = match.groups()
    if system == "ios":
        return f"{g[0]}.{g[1]}({g[2]}){g[3]}", int(g[4] or 0), g[5]
    if system == "iosxe":
        return f"{g[0]}.{g[1]}", int(g[2]), g[3]
    if system == "iosxr":
        # 7.11.21 is the first rebuild of 7.11.2.
        third = g[2]
        return f"{g[0]}.{g[1]}", int(third[0]), third[1:]
    if system == "nxos":
        return f"{g[0]}.{g[1]}", int(g[2]), g[3]
    return f"{g[0]}.{g[1]}", int(g[2]), g[3] or ""


def is_version(system: str, version: str) -> bool:
    return bool(PARTS[system].match(version))


def branch_of(system: str, version: str) -> str:
    return parts(system, version)[0]


def train_of(system: str, version: str) -> str:
    """The maintenance release a rebuild belongs to: 17.12.3 for 17.12.3a."""
    branch, maintenance, _ = parts(system, version)
    return f"{branch}#{maintenance}"


def is_rebuild(system: str, version: str) -> bool:
    return bool(parts(system, version)[2])


def branch_key(system: str, branch: str) -> Tuple:
    numbers = [int(n) for n in re.findall(r"\d+", branch)]
    letters = re.sub(r"[\d.()]", "", branch)
    return (*numbers, letters)


def version_key(system: str, version: str) -> Tuple:
    branch, maintenance, rebuild = parts(system, version)
    rebuild_key = (0, 0, "") if not rebuild else (1, int(rebuild), "") if rebuild.isdigit() else (1, 0, rebuild)
    return (*branch_key(system, branch), maintenance, *rebuild_key)


def in_scope(system: str, version: str) -> bool:
    numbers = tuple(int(n) for n in re.findall(r"\d+", version)[:2])
    return numbers >= FLOORS[system]


def find_versions(system: str, text: str) -> List[str]:
    """The releases a text names, in order, without repetition."""
    found = []
    for match in FINDERS[system].finditer(text):
        version = match.group(1)
        if is_version(system, version) and in_scope(system, version) and version not in found:
            found.append(version)
    return found


def only_out_of_scope(system: str, text: str) -> bool:
    """Whether a text names releases, all older than the scope of the site."""
    named = [m.group(1) for m in FINDERS[system].finditer(text) if is_version(system, m.group(1))]
    return bool(named) and not any(in_scope(system, version) for version in named)


def find_branch(system: str, text: str) -> Optional[str]:
    """The branch a text names as a whole, as "17.12" in "Cisco IOS XE 17.12.x"."""
    match = BRANCHES[system].search(text)
    return match.group(1) if match else None


def sort_versions(system: str, versions) -> List[str]:
    return sorted(versions, key=lambda version: version_key(system, version))
