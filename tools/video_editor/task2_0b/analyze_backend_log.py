#!/usr/bin/env python3
"""Read-only summary of Task 2.0B WPF and backend evidence."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


TIME_RE = re.compile(r"^(?P<ts>\S+)")
KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^ ]+)")
LOGGER_PID_RE = re.compile(r"\bINFO\s+(?P<pid>\d+)\s+\d+\s+mediastudio(?:\.|\s)")


def pid_is_running(pid: str) -> bool | None:
    try:
        if os.name == "nt":
            process = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, check=False,
            )
            if process.returncode != 0:
                return None
            for row in csv.reader(process.stdout.splitlines()):
                if len(row) > 1 and row[1].strip() == pid:
                    return True
            return False
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def line_time(line: str) -> datetime | None:
    match = TIME_RE.match(line)
    return parse_time(match.group("ts")) if match else None


def fields(line: str) -> dict[str, str]:
    return dict(KV_RE.findall(line))


def read_drag_records(path: Path | None, state_path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    offset = 0
    if state_path and state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            offset = int(state.get("dragLogByteOffset", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            offset = 0
    records: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        stream.seek(max(0, offset))
        for raw in stream:
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def ci(record: dict[str, Any], key: str, default: Any = None) -> Any:
    key_lower = key.lower()
    for candidate, value in record.items():
        if candidate.lower() == key_lower:
            return value
    return default


def parse_id_list(value: str | None) -> list[str]:
    return [item for item in (value or "").split(",") if item and item != "-"]


def analyze_backend(path: Path, since: datetime | None, project_filter: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "backendLog": str(path),
        "backendPidsStarted": [],
        "backendPidsExited": [],
        "backendPidsObserved": [],
        "backendPidsRunningAtAnalysis": {},
        "requests": {"begin": 0, "end": 0, "error": 0, "unmatchedCorrelationIds": []},
        "requestCorrelationIds": {"begin": [], "end": [], "error": []},
        "requestCountsByRoute": {},
        "saves": [],
        "mediaImports": [],
        "renderEvents": [],
        "errorLines": [],
    }
    begins: set[str] = set()
    ends: set[str] = set()
    routes: Counter[str] = Counter()
    observed_pids: set[str] = set()
    save_begin_by_corr: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, raw in enumerate(stream, 1):
            line = raw.rstrip("\r\n")
            timestamp = line_time(line)
            if since and timestamp and timestamp < since:
                continue
            data = fields(line)
            if "[backend process started]" in line and data.get("pid"):
                result["backendPidsStarted"].append({"pid": data["pid"], "time": timestamp.isoformat() if timestamp else None})
                observed_pids.add(data["pid"])
            logger_pid = LOGGER_PID_RE.search(line)
            if logger_pid:
                observed_pids.add(logger_pid.group("pid"))
            if "[backend process exited]" in line or "backend process exited" in line:
                result["backendPidsExited"].append({"pid": data.get("pid"), "exitCode": data.get("exitCode"), "time": timestamp.isoformat() if timestamp else None})
            if "video.request.begin" in line:
                result["requests"]["begin"] += 1
                correlation = data.get("correlation_id")
                if correlation:
                    begins.add(correlation)
                    result["requestCorrelationIds"]["begin"].append(correlation)
                route = f'{data.get("method", "?")} {data.get("path", "?")}'
                routes[route] += 1
            elif "video.request.end" in line:
                result["requests"]["end"] += 1
                if data.get("correlation_id"):
                    ends.add(data["correlation_id"])
                    result["requestCorrelationIds"]["end"].append(data["correlation_id"])
            elif "video.request.error" in line:
                result["requests"]["error"] += 1
                if data.get("correlation_id"):
                    result["requestCorrelationIds"]["error"].append(data["correlation_id"])
                if len(result["errorLines"]) < 100:
                    result["errorLines"].append({"line": line_number, "text": line[:500]})

            if "video.project.save.begin" in line:
                correlation = data.get("correlation_id", "")
                project_id = data.get("project_id", "")
                if not project_filter or project_id == project_filter:
                    save_begin_by_corr[correlation] = {
                        "time": timestamp.isoformat() if timestamp else None,
                        "timeObject": timestamp,
                        "correlationId": correlation,
                        "pid": data.get("pid"),
                        "projectId": project_id,
                        "requestRevision": _int_or_none(data.get("revision")),
                        "clipIds": parse_id_list(data.get("clip_ids")),
                        "mediaIds": parse_id_list(data.get("media_ids")),
                        "audioTrackIds": parse_id_list(data.get("audio_track_ids")),
                    }
            elif "video.project.save.end" in line:
                correlation = data.get("correlation_id", "")
                saved = save_begin_by_corr.pop(correlation, None)
                project_id = data.get("project_id", "")
                if saved and (not project_filter or project_id == project_filter):
                    saved["savedRevision"] = _int_or_none(data.get("revision"))
                    saved["endTime"] = timestamp.isoformat() if timestamp else None
                    saved.pop("timeObject", None)
                    result["saves"].append(saved)

            if "video.media.import" in line:
                result["mediaImports"].append({
                    "time": timestamp.isoformat() if timestamp else None,
                    "correlationId": data.get("correlation_id"),
                    "pid": data.get("pid"),
                    "mediaId": data.get("media_id"),
                    "kind": data.get("kind"),
                })

            if re.search(r"(?:Native )?Video job .* (?:completed|failed)|Video render job .* failed", line, re.IGNORECASE):
                result["renderEvents"].append({
                    "time": timestamp.isoformat() if timestamp else None,
                    "text": line[-500:],
                })
            if any(token in line.lower() for token in ("traceback", "critical", "uncaught exception", "access violation")):
                if len(result["errorLines"]) < 100:
                    result["errorLines"].append({"line": line_number, "text": line[:500]})
            elif re.search(r"\sERROR\s", line) and len(result["errorLines"]) < 100:
                result["errorLines"].append({"line": line_number, "text": line[:500]})

    result["requests"]["unmatchedCorrelationIds"] = sorted(begins - ends)
    result["backendPidsObserved"] = sorted(observed_pids, key=int)
    result["backendPidsRunningAtAnalysis"] = {
        pid: pid_is_running(pid) for pid in sorted(observed_pids, key=int)
    }
    result["requestCountsByRoute"] = dict(sorted(routes.items()))
    result["saves"].sort(key=lambda item: item.get("time") or "")
    result["revisionProgression"] = [
        {
            "time": item.get("time"),
            "projectId": item.get("projectId"),
            "correlationId": item.get("correlationId"),
            "requestRevision": item.get("requestRevision"),
            "savedRevision": item.get("savedRevision"),
            "clipCount": len(item.get("clipIds", [])),
        }
        for item in result["saves"]
    ]
    return result


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def summarize_drag(records: list[dict[str, Any]], saves: list[dict[str, Any]]) -> dict[str, Any]:
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        drag_id = str(ci(record, "DragSessionId", ""))
        if drag_id:
            sessions[drag_id].append(record)

    summaries: list[dict[str, Any]] = []
    for drag_id, items in sessions.items():
        items.sort(key=lambda item: str(ci(item, "Timestamp", "")))
        candidates = [
            item for item in items
            if str(ci(item, "Stage", "")) == "commit-candidate"
            and str(ci(item, "DropMode", "")).lower() == "replace"
        ]
        completions = [
            item for item in items
            if str(ci(item, "Stage", "")) == "commit-complete"
            and str(ci(item, "DropMode", "")).lower() == "replace"
        ]
        for candidate in candidates:
            target_id = ci(candidate, "TargetClipId")
            candidate_time = parse_time(str(ci(candidate, "Timestamp", "")))
            before = None
            after = None
            if target_id and candidate_time:
                for save in saves:
                    save_time = parse_time(save.get("time"))
                    if not save_time or save.get("projectId") is None:
                        continue
                    binding = dict(zip(save.get("clipIds", []), save.get("mediaIds", []))).get(target_id)
                    if save_time <= candidate_time:
                        before = binding
                    elif after is None:
                        after = binding
                        break
            change_confirmed = before is not None and after is not None and before != after
            summaries.append({
                "dragSessionId": drag_id,
                "targetClipId": target_id,
                "sourceMediaName": ci(candidate, "MediaName"),
                "time": ci(candidate, "Timestamp"),
                "state": "binding_changed_after_drop" if change_confirmed else "unverified_no_binding_change_observed",
                "bindingBefore": before,
                "bindingAfter": after,
                "commitCompleteStageObserved": bool(completions),
                "note": "The UI drag log marks the drop flow; the save snapshots establish whether the target binding changed. A completion stage alone is not treated as Replace confirmation.",
            })
    return {
        "dragRecordsRead": len(records),
        "dragSessionCount": len(sessions),
        "replaceDropCandidates": sum(
            1 for items in sessions.values() for item in items
            if str(ci(item, "Stage", "")) == "commit-candidate"
            and str(ci(item, "DropMode", "")).lower() == "replace"
        ),
        "replaceBindingChangesObserved": sum(1 for item in summaries if item["state"] == "binding_changed_after_drop"),
        "replaceSessions": summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-log", required=True, type=Path)
    parser.add_argument("--drag-log", type=Path)
    parser.add_argument("--session-state", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--since", help="ISO-8601 timestamp, filters backend records after this time")
    parser.add_argument("--out", type=Path, help="Optional path for a JSON summary (input logs remain unchanged)")
    args = parser.parse_args()
    since = parse_time(args.since)
    if not args.backend_log.is_file():
        parser.error(f"Backend log not found: {args.backend_log}")
    backend = analyze_backend(args.backend_log, since, args.project_id)
    drag_records = read_drag_records(args.drag_log, args.session_state)
    summary = {
        **backend,
        "dragLog": str(args.drag_log) if args.drag_log else None,
        "timelineDrag": summarize_drag(drag_records, backend["saves"]),
        "sourceLogsAreReadOnly": True,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
