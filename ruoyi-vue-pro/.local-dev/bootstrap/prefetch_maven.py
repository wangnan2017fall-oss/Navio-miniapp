#!/usr/bin/env python3
"""Bounded prefetch of public Maven Central JARs for already-cached POMs.

Reads only the project's dedicated repository. Downloads use private temporary
paths, verify Maven Central's SHA-1, then atomically install the JAR. Maven's
.part/.lastUpdated/checksum/provenance files are never modified or removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = HERE.parents[2] / ".local-runtime/maven-repository"
CENTRAL = "https://repo.maven.apache.org/maven2/"


def sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidates(repo: Path):
    found = []
    for pom in sorted(repo.rglob("*.pom")):
        jar = pom.with_suffix(".jar")
        if jar.is_file():
            continue
        try:
            doc = ET.parse(pom).getroot()
            packaging = next((node.text.strip() for node in doc
                              if node.tag.rsplit("}", 1)[-1] == "packaging" and node.text), "jar")
            if packaging == "pom" or "${" in packaging:
                continue
            # The path comes only from an existing POM under this dedicated repo.
            relative = jar.relative_to(repo)
            if any(piece in {"..", "."} for piece in relative.parts):
                continue
            found.append((pom, jar, relative))
        except (OSError, ET.ParseError, ValueError):
            # A POM that is still being written will be considered next scan.
            continue
    return found


def curl(url: str, output: Path, seconds: int):
    result = subprocess.run([
        "curl", "--noproxy", "*", "--location", "--fail", "--silent",
        "--show-error", "--connect-timeout", "10", "--max-time", str(seconds),
        "--output", str(output), "--write-out", "%{http_code}", url,
    ], capture_output=True, text=True)
    status = result.stdout.strip()
    return result.returncode, status


def fetch(jar: Path, relative: Path, work: Path):
    if jar.is_file():
        return "already_present", 0
    url = CENTRAL + "/".join(quote(part, safe="") for part in relative.parts)
    token = uuid.uuid4().hex
    checksum_temp = work / (token + ".sha1")
    jar_temp = work / (token + ".jar")
    code, status = curl(url + ".sha1", checksum_temp, 20)
    if status == "404":
        return "not_in_central", 0
    if code or status != "200":
        return "checksum_request_failed", 0
    content = checksum_temp.read_text(errors="replace").strip()
    expected = re.search(r"\b([a-fA-F0-9]{40})\b", content)
    if not expected:
        return "invalid_checksum_file", 0
    expected = expected.group(1).lower()
    if jar.is_file() and sha1(jar) == expected:
        return "already_present", 0
    code, status = curl(url, jar_temp, 60)
    if status == "404":
        return "not_in_central", 0
    if code or status != "200":
        return "jar_request_failed", 0
    if sha1(jar_temp) != expected:
        return "checksum_mismatch", 0
    size = jar_temp.stat().st_size
    # A concurrent Maven process may have finished the same immutable artifact.
    if jar.is_file() and sha1(jar) == expected:
        return "already_present", 0
    # Both locations are on the same filesystem. This never touches Maven's
    # .part files and a reader sees either the existing file or the verified JAR.
    os.replace(jar_temp, jar)
    return "installed_verified", size


def run(repo: Path, seconds: int, workers: int):
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError("Dedicated Maven repository does not exist: " + str(repo))
    work = HERE / "prefetch-temp" / uuid.uuid4().hex
    work.mkdir(parents=True)
    deadline = time.monotonic() + seconds
    counts = Counter()
    pending = deque()
    seen = set()
    futures = {}
    total_bytes = 0
    next_scan = 0.0
    next_report = 0.0
    start = time.monotonic()

    def report(phase):
        print(json.dumps({
            "phase": phase, "elapsedSeconds": round(time.monotonic() - start),
            "verifiedInstalled": counts["installed_verified"],
            "alreadyPresent": counts["already_present"],
            "skipped404": counts["not_in_central"],
            "failed": sum(v for k, v in counts.items()
                          if k not in {"installed_verified", "already_present", "not_in_central"}),
            "downloadedMiB": round(total_bytes / 1024 / 1024, 1),
            "active": len(futures), "queued": len(pending),
            "candidatePomsSeen": len(seen),
        }), flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_scan:
                for pom, jar, relative in candidates(repo):
                    key = str(relative)
                    if key not in seen:
                        seen.add(key)
                        pending.append((jar, relative))
                next_scan = now + 5
            for future in list(futures):
                if future.done():
                    try:
                        status, size = future.result()
                    except Exception:
                        status, size = "local_worker_error", 0
                    counts[status] += 1
                    total_bytes += size
                    del futures[future]
            while pending and len(futures) < workers:
                jar, relative = pending.popleft()
                futures[pool.submit(fetch, jar, relative, work)] = relative
            if now >= next_report:
                report("running")
                next_report = now + 30
            time.sleep(1)
        # No new requests after the bounded scan period. In-flight requests have
        # a 20-second checksum and 60-second artifact timeout.
        for future in list(futures):
            try:
                status, size = future.result()
            except Exception:
                status, size = "local_worker_error", 0
            counts[status] += 1
            total_bytes += size
            del futures[future]
    report("complete")
    print(json.dumps({"results": dict(counts), "repository": str(repo),
                      "privateTemporaryDirectory": str(work)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--seconds", type=int, default=210)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8 or not 1 <= args.seconds <= 300:
        raise ValueError("workers must be 1..8 and seconds must be 1..300")
    run(args.repository, args.seconds, args.workers)
