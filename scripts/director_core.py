"""Offline, deterministic helpers. They do not direct, generate images, or call providers."""
from __future__ import annotations
import base64
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

VERSION = "3.0.0"
ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 32 * 1024 * 1024
EPS = 1e-6

class ContractError(ValueError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(data):
    if not isinstance(data, bytes):
        data = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()

def load_json(path):
    p = Path(path)
    if p.stat().st_size > MAX_FILE:
        raise ContractError(f"JSON exceeds {MAX_FILE} bytes: {p}")
    def invalid(value):
        raise ContractError(f"Non-finite JSON value: {value}")
    return json.loads(p.read_text(encoding="utf-8-sig"), parse_constant=invalid)

def write_json(path, data, overwrite=False):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", overwrite)

def write_text(path, text, overwrite=False):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as f:
        f.write(text)

def num(v):
    if not isinstance(v, (int, float)) or isinstance(v, bool): return False
    try: return math.isfinite(v)
    except (OverflowError, ValueError): return False

def safe_id(s):
    return isinstance(s, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", s)) and ".." not in s

def text(v):
    return isinstance(v, str) and bool(v.strip())

def bi(zh="", en=""):
    return {"zh": zh, "en": en}

def lt(v, lang, required=True):
    s = v.get(lang, "") if isinstance(v, dict) else ""
    if required and not text(s):
        raise ContractError(f"Missing {lang} visual text. Ask the directing agent to complete the contract; the compiler does not translate or invent it.")
    return s.strip() if isinstance(s, str) else ""

def project_path(root, rel):
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        raise ContractError("An asset path must be a nonempty project-relative string")
    # Reject Windows absolute/drive paths even when validating on Linux.
    if re.match(r"^[A-Za-z]:", rel) or rel.startswith(("/", "\\")) or "://" in rel:
        raise ContractError(f"Use a project-relative path, not an absolute path or URL: {rel}")
    base = Path(root).resolve()
    p = (base / rel.replace("\\", "/")).resolve()
    if not p.is_relative_to(base):
        raise ContractError(f"Path escapes project root: {rel}")
    return p

ALIASES = {
    "source_shot_no": ["镜号", "镜头号", "分镜号", "序号", "分镜序号", "shot", "shotno", "shotid", "shot_id"],
    "duration_sec": ["时长", "时长(秒)", "时长（秒）", "时长/秒", "持续时间", "duration", "durationsec", "duration_sec"],
    "angle": ["摄影角度", "拍摄角度", "机位", "angle", "cameraangle"],
    "shot_size": ["景别", "shotsize", "shot_size"],
    "action": ["画面内容", "画面", "动作", "内容", "shot/action", "action", "description"],
    "scene": ["场景", "地点", "scene", "location"],
    "sound": ["声音", "对白", "台词", "dialogue", "sound", "audio"],
    "notes": ["备注", "运镜", "运镜/备注", "notes", "notes/visuals"],
    "narrative_intent": ["叙事目的", "镜头目的", "叙事意图", "narrativeintent", "narrative_intent"],
    "video_prompt": ["视频提示词", "prompt", "videoprompt"]
}

def hn(s):
    return re.sub(r"\s+", "", str(s or "")).lower()

def map_headers(row):
    out = {}
    for i, h in enumerate(row):
        for name, variants in ALIASES.items():
            if hn(h) in variants:
                if name in out:
                    raise ContractError(f"Ambiguous duplicate column for {name}: {row}")
                out[name] = i
    return out

def clock(s):
    bits = [float(x) for x in s.split(":")]
    if len(bits) not in (2, 3) or any(x < 0 or not math.isfinite(x) for x in bits) or any(x >= 60 for x in bits[1:]):
        raise ContractError(f"Invalid timecode: {s}")
    return sum(v * 60 ** i for i, v in enumerate(reversed(bits)))

def duration(value):
    if num(value):
        result = float(value)
    else:
        s = str(value).strip()
        m = re.fullmatch(r"(\d+(?::\d{1,2}){1,2}(?:\.\d+)?)\s*[-–—~至]\s*(\d+(?::\d{1,2}){1,2}(?:\.\d+)?)", s)
        if m:
            result = clock(m[2]) - clock(m[1])
        elif re.fullmatch(r"\d+(?::\d{1,2}){1,2}(?:\.\d+)?", s):
            result = clock(s)
        else:
            m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:秒|s|sec|seconds?)?", s, re.I)
            if not m:
                raise ContractError(f"Ambiguous duration {value!r}; specify an exact number of seconds (not a range or formula)")
            result = float(m[1])
    if not math.isfinite(result) or result <= 0:
        raise ContractError(f"Duration must be finite and positive: {value!r}")
    return result

def xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ContractError("DTD/entity declarations are not allowed in XLSX XML")
    return ET.fromstring(data)

def xlsx_tables(path):
    """Read stored worksheet cells only: no macros, formulas, links or Excel execution."""
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    relns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > 100 * 1024 * 1024:
            raise ContractError("XLSX decompression limit exceeded")
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in xml(z.read("xl/sharedStrings.xml")).findall("s:si", ns):
                shared.append("".join(n.text or "" for n in si.iter(f"{{{ns['s']}}}t")))
        rels = {r.attrib["Id"]: r.attrib for r in xml(z.read("xl/_rels/workbook.xml.rels"))}
        tables = {}
        for sheet in xml(z.read("xl/workbook.xml")).findall("s:sheets/s:sheet", ns):
            rel = rels[sheet.attrib[f"{{{relns}}}id"]]
            if rel.get("TargetMode") == "External":
                raise ContractError("External worksheet relationships are not supported")
            target = rel["Target"].replace("\\", "/")
            member = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if ".." in member.split("/"):
                raise ContractError("Unsafe worksheet relationship")
            rows = []
            for row in xml(z.read(member)).findall("s:sheetData/s:row", ns):
                rownum = int(row.attrib.get("r", len(rows) + 1))
                if rownum > 100000:
                    raise ContractError("Worksheet row limit exceeded")
                cells = {}
                for c in row.findall("s:c", ns):
                    letters = re.match(r"([A-Z]+)", c.attrib.get("r", "A1"))[1]
                    col = 0
                    for ch in letters:
                        col = col * 26 + ord(ch) - 64
                    if col > 1024:
                        raise ContractError("Worksheet column limit exceeded")
                    v = c.find("s:v", ns)
                    if c.find("s:f", ns) is not None:
                        value = "=" + (c.find("s:f", ns).text or "")
                    elif c.attrib.get("t") == "s":
                        value = shared[int(v.text)] if v is not None else ""
                    elif c.attrib.get("t") == "inlineStr":
                        value = "".join(n.text or "" for n in c.iter(f"{{{ns['s']}}}t"))
                    else:
                        value = v.text if v is not None and v.text is not None else ""
                    cells[col - 1] = value
                vals = [cells.get(i, "") for i in range(max(cells, default=-1) + 1)]
                rows.append((rownum, vals))
            tables[sheet.attrib["name"]] = rows
        return tables

def ingest(path, project_name=None, sheet_name=None, header_row=None):
    p = Path(path)
    if p.stat().st_size > MAX_FILE:
        raise ContractError("Input file size limit exceeded")
    ext = p.suffix.lower()
    if ext == ".xlsx":
        tables = xlsx_tables(p)
    elif ext == ".csv":
        data = p.read_bytes()
        try:
            body = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            body = data.decode("gb18030")
        tables = {"CSV": list(enumerate(csv.reader(io.StringIO(body)), 1))}
    elif ext == ".json":
        d = load_json(p)
        if "headers" not in d or "rows" not in d:
            raise ContractError("JSON input requires {headers: [...], rows: [[...]]}; a legacy board manifest is not a source table")
        tables = {"JSON": list(enumerate([d["headers"]] + d["rows"], 1))}
    else:
        raise ContractError("Supported input types: .xlsx, .csv, .json (headers/rows)")
    candidates = []
    for name, rows in tables.items():
        if sheet_name and name != sheet_name:
            continue
        for idx, (rn, vals) in enumerate(rows[:50]):
            if header_row and rn != header_row:
                continue
            cols = map_headers(vals)
            if all(k in cols for k in ("source_shot_no", "duration_sec", "action")):
                candidates.append((name, rows, idx, cols))
                break
    if len(candidates) != 1:
        raise ContractError(f"Expected one shot-list sheet; found {len(candidates)}. Sheets={list(tables)}. Use --sheet / --header-row, or rename required columns to 镜号、时长、画面内容.")
    name, rows, idx, cols = candidates[0]
    headers = [str(x or "") for x in rows[idx][1]]
    shots, ignored, warnings = [], [], []
    seen = set()
    for rn, vals in rows[idx + 1:]:
        if not any(str(x or "").strip() for x in vals):
            continue
        def cell(k):
            pos = cols.get(k, -1)
            return str(vals[pos]).strip() if 0 <= pos < len(vals) and vals[pos] is not None else ""
        sn = cell("source_shot_no")
        if hn(sn) in ALIASES["source_shot_no"]:
            ignored.append({"row": rn, "reason": "repeated_header"}); continue
        if sn in ("合计", "总计", "TOTAL", "总时长"):
            ignored.append({"row": rn, "reason": "explicit_total_row"}); continue
        if not sn:
            raise ContractError(f"{name} row {rn} has content but no shot number; no silent skipping")
        if sn in seen:
            raise ContractError(f"Duplicate source shot number {sn} at row {rn}")
        seen.add(sn)
        try:
            dur = duration(cell("duration_sec"))
        except ContractError as e:
            raise ContractError(f"{name} row {rn}: {e}") from e
        if not cell("action"):
            raise ContractError(f"{name} row {rn}: empty action")
        shot = {k: cell(k) for k in ALIASES if k not in ("duration_sec",)}
        shot.update(duration_sec=dur, source_row=rn, raw_cells={h or f"column_{i+1}": vals[i] if i < len(vals) else "" for i, h in enumerate(headers)})
        shots.append(shot)
    if not shots:
        raise ContractError("No source shots")
    numeric_ids = [int(s["source_shot_no"]) for s in shots if s["source_shot_no"].isdigit()]
    if len(numeric_ids) == len(shots) and any(b != a + 1 for a, b in zip(numeric_ids, numeric_ids[1:])):
        warnings.append("Non-consecutive numeric IDs retained in original row order; confirm whether this is an intentional excerpt.")
    return {"schema_version": VERSION, "project_name": project_name or p.stem,
            "source_file": p.name, "source_sha256": digest(p.read_bytes()), "sheet": name,
            "header_row": rows[idx][0], "headers": headers, "shots": shots,
            "shot_count": len(shots), "total_duration_sec": sum(s["duration_sec"] for s in shots),
            "ignored_rows": ignored, "warnings": warnings,
            "reader_limits": "Stored cells only; formulas are not evaluated; merged scene cells are not inferred; numeric durations mean seconds."}

def skeleton(source):
    shots = []
    for i, s in enumerate(source["shots"], 1):
        d = s["duration_sec"]
        shots.append({"shot_id": f"S{i:03d}", "source_shot_no": s["source_shot_no"],
            "source_span_sec": [0, d], "duration_sec": d, "scene_id": "UNRESOLVED",
            "status": "draft", "director": {"viewing_task": "", "visible_change": "", "why_this_camera": "", "hidden_viewpoint_check": ""},
            "subjects": [], "reference_asset_ids": [],
            "camera": {"shot_size_start": s.get("shot_size", ""), "shot_size_end": "", "height": "", "angle": s.get("angle", ""),
                       "lens_mm": None, "fov_deg": None, "movement": "UNRESOLVED", "observable_evidence": "", "focus": "", "composition": ""},
            "continuity": {"axis_id": "UNRESOLVED", "axis_side": "unknown", "screen_direction": "unknown", "entry_state": {}, "exit_state": {}, "exceptions": [], "lookahead_source_shots": []},
            "opening": bi(), "ending": bi(),
            "beats": [{"start_sec": 0, "end_sec": d, "trigger": "", "action": bi(), "camera": bi(), "sound": bi()}],
            "dialogue": [], "soundscape": bi(), "music": bi("无画外配乐。", "N/A"), "constraints": bi(),
            "keyframes": [{"id": f"S{i:03d}-{phase}", "phase": phase, "time_sec": t,
                "visible_state": bi(), "reference_asset_ids": [], "image_path": None,
                "generation_receipt": None, "visual_review": {"status": "unreviewed", "evidence": ""}}
                for phase, t in [("entry", 0), ("exit", d)]]})
    return {"schema_version": VERSION, "project": {"name": source["project_name"], "aspect_ratio": "16:9", "style": bi(), "source_sha256": source["source_sha256"]},
            "policy": {"board_max_duration_sec": 15, "edit_mode": "preserve_shots", "recut_approval": ""},
            "source_shots": source["shots"], "assets": [], "shots": shots,
            "review": {"director": "pending", "visual": "pending", "video": "not_generated", "user": "pending"}}

def shape_errors(doc):
    """Dependency-free validator for the vocabulary used by our bundled schema.

    It is not a general JSON Schema implementation. Keep vocabulary support in
    sync with the schema; all consumers call this before indexing fields.
    """
    schema = load_json(ROOT / "schemas/director-contract.schema.json")
    def walk(value, rule, path):
        errors = []
        def fail(code, message):
            errors.append({"code": code, "where": path, "message": message})
        if "$ref" in rule:
            target = schema
            for part in rule["$ref"].split("/")[1:]: target = target[part]
            errors.extend(walk(value, target, path))
        if "anyOf" in rule and not any(not walk(value, r, path) for r in rule["anyOf"]):
            fail("TYPE", "No permitted schema alternative matches")
            return errors
        types = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
                 "string": lambda v: isinstance(v, str), "number": num,
                 "integer": lambda v: num(v) and float(v).is_integer(),
                 "boolean": lambda v: isinstance(v, bool), "null": lambda v: v is None}
        expected = rule.get("type", [])
        if isinstance(expected, str): expected = [expected]
        if expected and not any(types[t](value) for t in expected):
            fail("TYPE", "Expected " + "/".join(expected)); return errors
        if "const" in rule and value != rule["const"]: fail("CONST", "Unexpected constant")
        if "enum" in rule and value not in rule["enum"]: fail("ENUM", "Unsupported value")
        if isinstance(value, dict):
            for key in rule.get("required", []):
                if key not in value: fail("REQUIRED", "Missing " + key)
            props = rule.get("properties", {})
            for key, item in value.items():
                if key in props: errors.extend(walk(item, props[key], path + "." + key))
                elif rule.get("additionalProperties") is False: fail("FIELD", "Unknown field " + key)
                elif isinstance(rule.get("additionalProperties"), dict): errors.extend(walk(item, rule["additionalProperties"], path + "." + key))
        if isinstance(value, list):
            if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", float("inf")):
                fail("LENGTH", "Array length outside schema bounds")
            for i, item in enumerate(value): errors.extend(walk(item, rule.get("items", {}), f"{path}[{i}]"))
        if isinstance(value, str):
            if len(value) < rule.get("minLength", 0): fail("LENGTH", "String is too short")
            if "pattern" in rule and not re.search(rule["pattern"], value): fail("PATTERN", "String does not match schema pattern")
        if num(value):
            if value < rule.get("minimum", -float("inf")) or value > rule.get("maximum", float("inf")) or value <= rule.get("exclusiveMinimum", -float("inf")):
                fail("RANGE", "Number outside schema bounds")
        return errors
    return walk(doc, schema, "$")


def source_integrity(doc, source, stage, err, warn):
    """Check explicit human-classified speech against a separately held source.

    This does not infer speech from sound prose or authenticate reviewer identity.
    The caller must obtain the independent snapshot from trusted storage.
    """
    if source is None:
        (err if stage == "production" else warn)("SOURCE_BASELINE_REQUIRED", "source_shots", "Supply an independently retained source snapshot; embedded source rows alone are not provenance proof")
    elif not isinstance(source, dict) or not isinstance(source.get("shots"), list):
        err("SOURCE_BASELINE_INVALID", "source", "Expected an independent imported source snapshot")
    elif (doc["project"]["source_sha256"] != source.get("source_sha256") or
          digest(doc["source_shots"]) != digest(source["shots"])):
        err("SOURCE_SNAPSHOT_CHANGED", "source_shots", "Contract differs from independently retained source snapshot")
    for src in doc["source_shots"]:
        sn = src["source_shot_no"]
        baseline = src.get("dialogue_baseline")
        if baseline is None:
            (err if stage == "production" else warn)("DIALOGUE_BASELINE_REQUIRED", sn, "Classify source speech explicitly; no dialogue coverage claim is possible for this legacy source")
            continue
        if baseline["status"] != "reviewed" or not text(baseline["reviewed_by"]) or not text(baseline["evidence"]):
            err("DIALOGUE_BASELINE_REVIEW", sn, "Explicit reviewed speech classification and evidence required")
        expected, last_end = [], 0
        for line in baseline["lines"]:
            start, end = map(int, line["sound_span"])
            if not safe_id(line["id"]) or line["id"] in expected: err("DIALOGUE_BASELINE_ID", sn, "Duplicate/unsafe source speech ID")
            if start < last_end or not start < end <= len(src["sound"]) or src["sound"][start:end] != line["text"]:
                err("DIALOGUE_BASELINE_SPAN", sn, "Speech must match ordered non-overlapping exact character spans of original sound")
            expected.append(line["id"]); last_end = end
        by_id = {q["id"]: q for q in baseline["lines"]}
        actual = []
        for shot in doc["shots"]:
            if shot["source_shot_no"] != sn: continue
            for q in sorted(shot["dialogue"], key=lambda q: q["start_sec"]):
                qid = q.get("source_dialogue_id")
                actual.append(qid)
                if qid not in by_id or q["text"] != by_id[qid]["text"]:
                    err("DIALOGUE_SOURCE_MAPPING", shot["shot_id"], "Spoken line must reference an exact classified source line")
        if actual != expected:
            err("DIALOGUE_COVERAGE", sn, "Source speech must occur exactly once in original order; omissions, duplicates and unapproved revisions are blocked")


def frame_binding(frame):
    receipt = frame.get("generation_receipt") or {}
    generated = receipt.get("output_sha256")
    reviewed = frame["visual_review"].get("reviewed_sha256")
    if not isinstance(generated, str) or not re.fullmatch(r"[a-f0-9]{64}", generated):
        raise ContractError(f"{frame['id']}: generation output SHA-256 is required")
    if frame["visual_review"]["status"] != "passed" or not text(frame["visual_review"]["evidence"]) or reviewed != generated:
        raise ContractError(f"{frame['id']}: passed visual review must bind reviewed_sha256 to generation output SHA-256")
    return generated


def frame_inputs(frame, assetmap, root):
    receipt = frame.get("generation_receipt") or {}
    used = receipt.get("input_asset_ids", [])
    if not text(receipt.get("tool_call_id")) or not set(frame["reference_asset_ids"]).issubset(used) or len(set(used)) != len(used):
        raise ContractError(f"{frame['id']}: generation receipt must identify all expected input assets and a tool call")
    hashes = receipt.get("input_asset_sha256", {})
    for aid in used:
        expected = hashes.get(aid)
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ContractError(f"Missing generation-time input SHA-256 for {aid}")
        asset = assetmap.get(aid)
        if not asset or not root or check_files([{**asset, "sha256": expected}], root):
            raise ContractError(f"Missing generation-time input asset {aid}")


def verify_media(path, kind):
    """Reject empty files and fully decode raster images when Pillow is present.

    Audio/video codec validity is not certified by this offline checker.
    """
    if path.stat().st_size == 0: raise ContractError(f"Empty media file: {path}")
    if kind == "image":
        try:
            from PIL import Image
        except ImportError as exc:
            raise ContractError("Image integrity checking requires Pillow; do not claim undecoded image bytes are valid") from exc
        try:
            with Image.open(path) as im:
                if im.width * im.height > 40_000_000: raise ContractError("Image exceeds 40 megapixel safety limit")
                im.verify()
            with Image.open(path) as im: im.load()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            raise ContractError(f"Invalid or unsupported raster image: {path}") from exc

def validate(doc, stage="plan", asset_root=None, source=None):
    errors, warnings = [], []
    def err(code, where, msg): errors.append({"code": code, "where": where, "message": msg})
    def warn(code, where, msg): warnings.append({"code": code, "where": where, "message": msg})
    if not isinstance(doc, dict):
        return {"ok": False, "errors": [{"code": "TYPE", "where": "$", "message": "Expected object"}], "warnings": []}
    errors.extend(shape_errors(doc))
    if errors: return {"ok": False, "errors": errors, "warnings": warnings}
    if stage not in ("plan", "production"): err("STAGE", "$", "Unknown validation stage")
    for k in ("project", "policy", "source_shots", "assets", "shots", "review"):
        if k not in doc: err("REQUIRED", "$", k)
    if errors: return {"ok": False, "errors": errors, "warnings": warnings}
    if doc.get("schema_version") != VERSION: err("VERSION", "$", f"Expected {VERSION}")
    if not all(isinstance(doc[k], list) for k in ["source_shots", "assets", "shots"]):
        err("TYPE", "$", "source_shots, assets and shots must be arrays")
        return {"ok": False, "errors": errors, "warnings": warnings}
    source_integrity(doc, source, stage, err, warn)
    policy = doc.get("policy", {})
    cap = policy.get("board_max_duration_sec")
    if not num(cap) or cap <= 0 or cap > 15: err("BOARD_CAP", "policy", "Human review boards must be >0 and <=15 seconds")
    if policy.get("edit_mode") not in ("preserve_shots", "approved_recut"): err("EDIT_MODE", "policy", "Unknown edit mode")
    if policy.get("edit_mode") == "approved_recut" and not text(policy.get("recut_approval")):
        err("RECUT_APPROVAL", "policy", "A recut requires a recorded user approval")
    sources = {}
    for s in doc["source_shots"]:
        sn = s.get("source_shot_no")
        if not isinstance(sn, str) or not sn or sn in sources: err("SOURCE_ID", "source_shots", "Missing/duplicate string source ID")
        if not num(s.get("duration_sec")) or s["duration_sec"] <= 0: err("SOURCE_DURATION", str(sn), "Invalid duration")
        sources[sn] = s
    assetmap = {}
    for a in doc["assets"]:
        aid = a.get("id")
        if not safe_id(aid) or aid in assetmap: err("ASSET_ID", "assets", str(aid))
        assetmap[aid] = a
        if a.get("role") not in ROLE_ZH: err("ASSET_ROLE", str(aid), "Select a supported, explicit reference role; review boards are not model assets")
        if a.get("kind") not in ("image", "video", "audio"): err("ASSET_KIND", str(aid), "image/video/audio required")
        if a.get("path"):
            try: project_path(asset_root or ".", a["path"])
            except ContractError as e: err("ASSET_PATH", str(aid), str(e))
    seen, groups, actual_order, global_frame_ids = set(), {}, [], set()
    if not doc["shots"]: err("EMPTY", "shots", "No shots")
    for s in doc["shots"]:
        sid = s.get("shot_id", "?"); sn = s.get("source_shot_no")
        if not safe_id(sid) or sid in seen: err("SHOT_ID", str(sid), "Missing/unsafe/duplicate shot ID")
        seen.add(sid)
        if sn not in sources: err("SOURCE_REF", str(sid), str(sn))
        groups.setdefault(sn, []).append(s)
        if not actual_order or sn != actual_order[-1]: actual_order.append(sn)
        d = s.get("duration_sec")
        if not num(d) or d <= 0:
            err("DURATION", sid, "Expected positive finite seconds"); continue
        span = s.get("source_span_sec")
        if not isinstance(span, list) or len(span) != 2 or not all(num(v) for v in span) or span[0] < 0 or abs(span[1] - span[0] - d) > EPS:
            err("SOURCE_SPAN", sid, "Source span must be ordered and equal shot duration")
        if s.get("status") not in ("planned", "generated_unverified", "reviewed"):
            err("DRAFT", sid, "Director must resolve the imported skeleton before compilation")
        if not text(s.get("scene_id")) or s.get("scene_id") == "UNRESOLVED": err("SCENE", sid, "Resolve scene identity")
        for field in ("viewing_task", "visible_change", "why_this_camera", "hidden_viewpoint_check"):
            if not text(s.get("director", {}).get(field)): err("DIRECTOR_DECISION", sid, field)
        for field in ("shot_size_start", "shot_size_end", "height", "angle", "movement", "observable_evidence", "focus", "composition"):
            if not text(s.get("camera", {}).get(field)) or s["camera"][field] == "UNRESOLVED": err("CAMERA_DECISION", sid, field)
        for field in ("lens_mm", "fov_deg"):
            v = s.get("camera", {}).get(field)
            if v is not None and (not num(v) or v <= 0 or (field == "fov_deg" and v >= 180)): err("OPTICS", sid, field)
        subjects = s.get("subjects", [])
        if not isinstance(subjects, list) or any(not safe_id(x) for x in subjects) or len(set(subjects)) != len(subjects): err("SUBJECTS", sid, "Expected unique entity IDs")
        for field in ("opening", "ending", "soundscape", "music", "constraints"):
            if not text(s.get(field, {}).get("zh")): err("VISUAL_TEXT", sid, field + ".zh")
        refs = s.get("reference_asset_ids", [])
        if not isinstance(refs, list) or len(set(refs)) != len(refs): err("ASSET_REFS", sid, "Reference IDs must be unique")
        for aid in refs:
            if aid not in assetmap: err("ASSET_REF", sid, str(aid))
        beats = s.get("beats", [])
        if not isinstance(beats, list) or not beats:
            err("BEATS", sid, "At least one continuous beat required"); beats = []
        end = 0
        for b in beats:
            a, z = b.get("start_sec"), b.get("end_sec")
            if not num(a) or not num(z) or abs(a - end) > EPS or z <= a or z > d + EPS:
                err("BEAT_TIMELINE", sid, "Beats must be continuous, increasing and cover the duration")
            if num(z): end = z
            if not text(b.get("trigger")): err("TRIGGER", sid, "Use an observable trigger or deliberate hold")
            for f in ("action", "camera", "sound"):
                if not text(b.get(f, {}).get("zh")): err("BEAT_TEXT", sid, f + ".zh")
        if abs(end - d) > EPS: err("BEAT_END", sid, "Final beat must end at shot duration")
        for line in s.get("dialogue", []):
            a, z = line.get("start_sec"), line.get("end_sec")
            if not num(a) or not num(z) or not 0 <= a < z <= d + EPS: err("DIALOGUE_TIME", sid, "Dialogue outside shot")
            if not text(line.get("text")) or not safe_id(line.get("speaker_id")): err("DIALOGUE", sid, "Exact text and stable speaker ID required")
            if line.get("text") and line["text"] not in str(sources.get(sn, {}).get("sound", "")):
                err("DIALOGUE_SOURCE", sid, "Spoken text is not an exact excerpt of the source sound column; obtain explicit source revision first")
            if num(a) and num(z) and z > a and text(line.get("text")):
                han = len(re.findall(r"[\u3400-\u9fff]", line["text"]))
                if han / (z - a) > 5.5: warn("SPEECH_RATE_REVIEW", sid, "Dense Mandarin dialogue: time an actual reading; do not silently shorten or accelerate")
        c = s.get("continuity", {})
        for f in ("axis_id", "axis_side", "screen_direction", "entry_state", "exit_state", "exceptions", "lookahead_source_shots"):
            if f not in c: err("CONTINUITY_FIELD", sid, f)
        if c.get("axis_side") not in ("A", "B", "on_axis", "not_applicable"): err("AXIS", sid, "Resolve axis side; not_applicable needs an explanation in camera evidence")
        if not isinstance(c.get("entry_state"), dict) or not isinstance(c.get("exit_state"), dict): err("WORLD_STATE", sid, "State snapshots must be objects")
        if stage == "production" and (not c.get("entry_state") or not c.get("exit_state")): err("WORLD_STATE", sid, "Production review requires explicit entry/exit state")
        frames = s.get("keyframes", [])
        if len(frames) < 2: err("KEYFRAMES", sid, "Use entry and exit; they may reuse the same image for an intentional hold")
        ids, prev_t = set(), -1
        for phase, at in [("entry", 0), ("exit", d)]:
            try:
                anchor = frame_at(s, phase)
                if abs(anchor["time_sec"] - at) > EPS: err("FRAME_ANCHOR", sid, phase)
            except ContractError as exc: err("FRAME_ANCHOR", sid, str(exc))
        for k in frames:
            kid = k.get("id", "?"); t = k.get("time_sec")
            if not safe_id(kid) or kid in global_frame_ids: err("FRAME_ID", sid, str(kid))
            ids.add(kid); global_frame_ids.add(kid)
            if not num(t) or not 0 <= t <= d or t < prev_t: err("FRAME_TIME", sid, str(kid))
            if num(t): prev_t = t
            if not text(k.get("visible_state", {}).get("zh")): err("FRAME_DESCRIPTION", sid, str(kid))
            for aid in k.get("reference_asset_ids", []):
                if aid not in assetmap: err("FRAME_REF", sid, str(aid))
            if k.get("image_path"):
                try: project_path(asset_root or ".", k["image_path"])
                except ContractError as e: err("FRAME_PATH", sid, str(e))
            if stage == "production":
                receipt = k.get("generation_receipt") or {}
                used = receipt.get("input_asset_ids", [])
                if not text(receipt.get("tool_call_id")) or not set(k.get("reference_asset_ids", [])).issubset(set(used)):
                    err("REFERENCE_RECEIPT", sid, f"{kid}: expected references are not supported by an actual generation receipt")
                try: frame_inputs(k, assetmap, asset_root)
                except (ContractError, OSError) as exc: err("INPUT_ASSET_INTEGRITY", sid, str(exc))
                if k.get("visual_review", {}).get("status") != "passed" or not text(k.get("visual_review", {}).get("evidence")):
                    err("VISUAL_REVIEW", sid, f"{kid}: human/VLM evidence is missing")
                if not asset_root:
                    err("ASSET_ROOT", sid, "--asset-root is required for production checks")
                else:
                    try:
                        expected_hash = frame_binding(k)
                        missing = check_files([{"id": kid, "kind": "image", "path": k.get("image_path"), "sha256": expected_hash}], asset_root)
                        if missing: err("FRAME_FILE", sid, str(kid))
                    except (ContractError, OSError) as exc: err("FRAME_INTEGRITY", sid, str(exc))
    expected_order = [s.get("source_shot_no") for s in doc["source_shots"]]
    if actual_order != expected_order: err("SOURCE_ORDER", "shots", "Preserve the original source order and cover every source shot exactly once as a contiguous partition")
    for sn, src in sources.items():
        parts = groups.get(sn, [])
        if policy.get("edit_mode") == "preserve_shots" and len(parts) != 1: err("UNAPPROVED_RECUT", str(sn), "One source shot must remain one camera shot")
        at = 0
        for s in parts:
            sp = s.get("source_span_sec", [])
            if len(sp) == 2 and all(num(v) for v in sp):
                if abs(sp[0] - at) > EPS: err("SOURCE_COVERAGE", str(sn), "Gap/overlap in source spans")
                at = sp[1]
        if num(src.get("duration_sec")) and abs(at - src["duration_sec"]) > EPS: err("SOURCE_TOTAL", str(sn), "Mapped duration differs from source")
    for prev, cur in zip(doc["shots"], doc["shots"][1:]):
        if prev.get("scene_id") != cur.get("scene_id"): continue
        a, b = prev.get("continuity", {}), cur.get("continuity", {})
        allowed = {e.get("field") for e in b.get("exceptions", []) if e.get("approved_by_user") is True and text(e.get("reason"))}
        ae, be = a.get("exit_state", {}), b.get("entry_state", {})
        if isinstance(ae, dict) and isinstance(be, dict):
            for key in set(ae) | set(be):
                if key not in ae or key not in be:
                    warn("STATE_COVERAGE", cur.get("shot_id"), f"{key}: appears on only one side of the cut; check off-screen continuity")
                elif ae[key] != be[key] and key not in allowed:
                    err("STATE_JUMP", cur.get("shot_id"), f"{key}: previous exit differs from current entry; compare actual frames before approving an exception")
        if a.get("axis_id") == b.get("axis_id") and {a.get("axis_side"), b.get("axis_side")} == {"A", "B"} and "axis_side" not in allowed:
            err("AXIS_CROSS", cur.get("shot_id"), "Unexplained axis crossing; record a visible bridge or user-approved intentional break")
    if stage == "production":
        for aid, a in assetmap.items():
            try:
                if not asset_root or check_files([dict(a)], asset_root):
                    err("ASSET_FILE", str(aid), "Actual local reference file missing")
            except (ContractError, OSError) as exc: err("ASSET_INTEGRITY", str(aid), str(exc))
        for field in ("director", "user"):
            if doc.get("review", {}).get(field) != "approved": err("APPROVAL", "review", field)
    return {"ok": not errors, "stage": stage, "errors": errors, "warnings": warnings,
            "source_baseline_sha256": digest(source) if source is not None else None,
            "limits": "Deterministic checks of explicit fields only. No image identity, natural-language equivalence, physical motion, aesthetics, or model execution is certified."}

def group_boards(doc):
    report = validate(doc)
    if not report["ok"]: raise ContractError(json.dumps(report, ensure_ascii=False))
    cap = doc["policy"]["board_max_duration_sec"]
    boards, cur, total = [], [], 0
    def flush():
        if cur:
            boards.append({"board_id": f"EB-{len(boards)+1:03d}", "shot_ids": [s["shot_id"] for s in cur],
                           "source_shot_nos": list(dict.fromkeys(s["source_shot_no"] for s in cur)), "total_duration_sec": round(total, 6), "scene_id": cur[0]["scene_id"]})
    for s in doc["shots"]:
        if s["duration_sec"] > cap + EPS:
            raise ContractError(f"{s['shot_id']} exceeds the human board cap ({cap}s). This grouper cannot paginate a continuous long take; use separate no-cut review windows without changing the contract. No automatic recut/padding.")
        if cur and (cur[-1]["scene_id"] != s["scene_id"] or total + s["duration_sec"] > cap + EPS):
            flush(); cur=[]; total=0
        cur.append(s); total += s["duration_sec"]
    flush()
    return {"schema_version": VERSION, "boards": boards, "total_duration_sec": sum(b["total_duration_sec"] for b in boards), "status": "planned_not_visually_verified"}

PROFILES = {
    "seedance-2.0": {"family": "seedance", "min_duration_sec": 4, "max_duration_sec": 15, "modes": ["T2V", "I2V", "FL2V", "REF"], "max_prompt_chars": 2000, "max_images": 9, "max_videos": 3, "max_audio": 3, "max_total_refs": 12},
    "seedance-2.5": {"family": "seedance", "min_duration_sec": 4, "max_duration_sec": 30, "modes": ["T2V", "I2V", "FL2V", "REF"], "max_prompt_chars": None, "max_images": 30, "max_videos": 10, "max_audio": 10, "max_total_refs": 50},
    "minimax-h3": {"family": "h3", "min_duration_sec": 4, "max_duration_sec": 15, "modes": ["T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"], "max_prompt_chars": None, "max_images": None, "max_videos": None, "max_audio": None, "max_total_refs": None}
}

ROLE_ZH = {"identity":"人物身份外观", "wardrobe":"服装", "scene":"场景结构与光线", "prop":"道具外观", "composition":"构图", "first_frame":"起始画面", "last_frame":"结束画面", "previous_frame":"前镜连续性", "camera_motion":"机位与运镜", "audio_style":"声音参考", "audio_reuse":"声音复用", "style":"画面风格"}

def selected_shots(doc, ids=None):
    shots = doc["shots"]
    if not ids: return shots
    if len(set(ids)) != len(ids): raise ContractError("Duplicate requested shot IDs")
    known = {s["shot_id"] for s in shots}
    if not set(ids).issubset(known): raise ContractError(f"Unknown shot IDs: {set(ids)-known}")
    selected = [s for s in shots if s["shot_id"] in ids]
    if [s["shot_id"] for s in selected] != ids: raise ContractError("Requested shots must follow the source order")
    indices = [shots.index(s) for s in selected]
    if indices != list(range(indices[0], indices[-1]+1)): raise ContractError("One video job must use a contiguous shot range")
    return selected

def frame_at(shot, phase):
    matches = [k for k in shot["keyframes"] if k["phase"] == phase]
    if len(matches) != 1: raise ContractError(f"Expected exactly one {phase} frame; found {len(matches)}")
    return matches[0]

def build_refs(doc, shots, family, mode):
    aset = {a["id"]: a for a in doc["assets"]}
    if mode in ("T2V", "T2VA"): return []
    if mode in ("I2V", "I2VA", "FL2V", "FL2VA", "L2VA"):
        frames=[]
        if mode != "L2VA": frames.append((shots[0], "entry", "first_frame"))
        if mode in ("FL2V", "FL2VA", "L2VA"): frames.append((shots[-1], "exit", "last_frame"))
        out=[]
        for s, phase, role in frames:
            k=frame_at(s,phase)
            out.append({"id": k["id"], "kind":"image", "role":role, "path": k.get("image_path"), "description":k["visible_state"], "entity_id":None, "sha256": (k.get("generation_receipt") or {}).get("output_sha256"), "used_in_shots":[s["shot_id"]], "at_sec":0 if role=="first_frame" else sum(x["duration_sec"] for x in shots)})
        return out
    ids = list(dict.fromkeys(a for s in shots for a in s["reference_asset_ids"]))
    out=[]
    for aid in ids:
        a = dict(aset[aid]);a["used_in_shots"]=[s["shot_id"] for s in shots if aid in s["reference_asset_ids"]]
        if a.get("role") in ("first_frame", "last_frame"):
            d=sum(x["duration_sec"] for x in shots)
            if not num(a.get("at_sec")) or not 0 <= a["at_sec"] <= d:
                raise ContractError(f"Timed keyframe reference {aid} requires at_sec within this generation job")
        if a.get("role") == "review_board": raise ContractError("A human review table is not a default video reference. Export clean keyframes instead.")
        out.append(a)
    if not out: raise ContractError("Reference mode requires an explicit reference selection; do not infer attachments from filenames in prose")
    return out

def assign_labels(refs, family):
    counts=Counter(); subjects={}; next_subject=0
    for a in refs:
        kind=a["kind"];counts[kind]+=1
        token={"image":"Image", "video":"Video", "audio":"Audio"}[kind]
        a["upload_label"] = f"@{token} {counts[kind]}" if family=="seedance" else f"<{ {'image':'Picture','video':'Video','audio':'Audio'}[kind]} {counts[kind]}>"
        a["content_label"] = a["upload_label"]
        if family=="h3" and a.get("role") in ("identity","wardrobe","scene","prop","style"):
            # Identity and costume can define one subject. Scene/style units remain distinct.
            key=a.get("entity_id") or a["id"]
            if key not in subjects:
                next_subject+=1;subjects[key]=f"<Subject {next_subject}>"
            a["content_label"]=subjects[key]
    return refs

def check_files(refs, root):
    missing=[]
    for a in refs:
        a["submitted"] = False
        if not a.get("path"):
            a["file_status"]="missing";missing.append(a["id"]);continue
        p=project_path(root,a["path"])
        if not p.is_file():
            a["file_status"]="missing";missing.append(a["id"]);continue
        a["file_status"]="present"
        if p.stat().st_size > 256 * 1024 * 1024: raise ContractError(f"Asset exceeds local hashing limit (256 MiB): {a['id']}")
        verify_media(p, a["kind"])
        a["actual_sha256"]=digest(p.read_bytes())
        if a.get("sha256") and a["sha256"]!=a["actual_sha256"]:
            raise ContractError(f"Asset changed since approval: {a['id']}")
    return missing

def replace_refs(s, refs):
    mapping={a["id"]:a["content_label"] for a in refs}
    def sub(m):
        if m[1] not in mapping: raise ContractError(f"Unbound reference placeholder {m[0]}")
        return mapping[m[1]]
    return re.sub(r"\{\{asset:([A-Za-z0-9_.-]+)\}\}",sub,s)

def compiler(doc, profile_id, mode, asset_root, ids=None, draft=False, char_limit=None, source=None):
    check=validate(doc, asset_root=asset_root, source=source)
    if not draft:
        for warning in check["warnings"]:
            if warning["code"] in ("SOURCE_BASELINE_REQUIRED", "DIALOGUE_BASELINE_REQUIRED"):
                check["errors"].append(warning)
                check["ok"] = False
    if not check["ok"]: raise ContractError(json.dumps(check,ensure_ascii=False))
    profile_path=ROOT/"profiles"/(profile_id+".json")
    if not safe_id(profile_id) or not profile_path.is_file(): raise ContractError("Unknown model profile")
    profile=load_json(profile_path)
    if mode not in profile["modes"]: raise ContractError(f"Mode {mode} is not declared in {profile_id}")
    shots=selected_shots(doc,ids);total=sum(s["duration_sec"] for s in shots)
    if not profile["min_duration_sec"] <= total <= profile["max_duration_sec"]:
        raise ContractError(f"Requested {total:g}s is outside {profile_id} {profile['min_duration_sec']}-{profile['max_duration_sec']}s. Do not pad or change source time; ask for an approved production plan.")
    if abs(total-round(total))>EPS:
        raise ContractError("Bundled delivery profiles use whole-second requests. Preserve the fractional edit duration and obtain an explicit provider/trim plan; do not silently round.")
    family=profile["family"];lang="en" if family=="h3" else "zh"
    refs=assign_labels(build_refs(doc,shots,family,mode),family)
    counts=Counter(a["kind"] for a in refs)
    for key,kind in [("max_images","image"),("max_videos","video"),("max_audio","audio")]:
        if profile.get(key) is not None and counts[kind]>profile[key]: raise ContractError(f"{key} exceeded; explicitly select relevant references")
    if profile.get("max_total_refs") is not None and len(refs)>profile["max_total_refs"]: raise ContractError("Combined reference count exceeded")
    if not draft and mode in ("I2V", "I2VA", "FL2V", "FL2VA", "L2VA"):
        selected_frames = []
        if mode != "L2VA": selected_frames.append(frame_at(shots[0], "entry"))
        if mode in ("FL2V", "FL2VA", "L2VA"): selected_frames.append(frame_at(shots[-1], "exit"))
        for frame in selected_frames:
            frame_binding(frame)
            frame_inputs(frame, {a["id"]: a for a in doc["assets"]}, asset_root)
    missing=check_files(refs,asset_root)
    if missing and not draft: raise ContractError(f"Missing actual image/reference files: {missing}. Use --draft only for a clearly marked offline draft.")
    def t(v,required=True): return replace_refs(lt(v,lang,required),refs)
    style=t(doc["project"]["style"])
    speech_events=[];offset=0
    for s in shots:
        for q in s.get("dialogue",[]): speech_events.append((offset+q["start_sec"],q["speaker_id"]))
        offset+=s["duration_sec"]
    speakers={name:f"S{i+1}" for i,name in enumerate(dict.fromkeys(name for _,name in sorted(speech_events,key=lambda event:event[0])))}
    passages=[];offset=0
    for i,s in enumerate(shots,1):
        if family=="h3":
            prefix="[Shot 1] " if i==1 else f"[Shot {i}] At {int(offset//60):02d}:{offset%60:06.3f}, the camera cuts to the following composition. "
        else: prefix=f"{offset:g}–{offset+s['duration_sec']:g}秒（镜头{i}）："
        bits=[prefix+t(s["opening"])]
        if mode in ("Ref2VA","REF"):
            uses=[a for a in refs if s["shot_id"] in a["used_in_shots"]]
            if uses:
                if family=="h3": bits.append("In this shot, "+"; ".join(f"{a['content_label']} guides {a.get('role','reference').replace('_',' ')}"+(f" at {a['at_sec']:g} seconds" if a.get('role') in ('first_frame','last_frame') else '') for a in uses)+".")
                else: bits.append("本镜参考职责："+"；".join(f"{a['content_label']}约束{ROLE_ZH.get(a.get('role'),a.get('role','参考'))}" for a in uses)+"。")
        for b in s["beats"]:
            if family=="h3": pre=f"From {offset+b['start_sec']:g} to {offset+b['end_sec']:g} seconds, "
            else: pre=f"{offset+b['start_sec']:g}–{offset+b['end_sec']:g}秒："
            bits.append(pre+" ".join([t(b["action"]),t(b["camera"]),t(b["sound"])]))
        for q in sorted(s.get("dialogue",[]),key=lambda x:x["start_sec"]):
            delivery=t(q.get("delivery",bi()))
            name=t(q.get("speaker_label",bi(q["speaker_id"],q["speaker_id"])))
            if family=="h3":
                bound=next((a['content_label'] for a in refs if a.get('entity_id')==q['speaker_id'] and a['content_label'].startswith('<Subject ')),None)
                if bound: name=bound
                verb={"onscreen": "says on screen with synchronized visible lip movement", "offscreen": "speaks from off screen within the scene", "voiceover": "narrates in a non-diegetic voiceover"}[q["mode"]]
                end=" Do not animate any visible character's lips for this line." if q["mode"] != "onscreen" else ""
                bits.append(f"From {offset+q['start_sec']:g} to {offset+q['end_sec']:g} seconds, {name} ({speakers[q['speaker_id']]}) {delivery} {verb}: <d>[{q.get('language','Mandarin')}] {q['text']}</d>.{end}")
            else:
                mode_text={"onscreen": "画内对白，发声人物口型与台词同步", "offscreen": "场景内画外对白，不为任何画内人物添加本句口型", "voiceover": "非叙事空间旁白，不为任何画内人物添加本句口型"}[q["mode"]]
                bits.append(f"{offset+q['start_sec']:g}–{offset+q['end_sec']:g}秒，{name}{delivery}（{mode_text}）：“{q['text']}”")
        bits.extend([t(s["ending"]),t(s["constraints"])])
        passages.append("\n".join(bits));offset+=s["duration_sec"]
    # Deduplicate whole soundscape paragraphs only, never truncate dialogue or action.
    sound=" ".join(dict.fromkeys(t(s["soundscape"]) for s in shots))
    music_values=list(dict.fromkeys(t(s["music"]) for s in shots))
    music=" ".join(music_values)
    if "N/A" in music_values and len(music_values)>1:
        raise ContractError("Mixed score/no-score phases need a manually aligned sound plan before merging this job")
    if family=="seedance":
        lines=[f"{total:g}秒，{doc['project']['aspect_ratio']}。{style}"]
        if mode in ("I2V","FL2V"):
            lines.append(f"{refs[0]['upload_label']}作为0秒首帧。")
            if mode=="FL2V": lines.append(f"{refs[-1]['upload_label']}作为{total:g}秒尾态；用连续动作连接，不把末帧状态提前。")
        elif mode=="REF":
            lines.append("参考职责："+"；".join(f"{a['upload_label']}用于{ROLE_ZH.get(a.get('role'),a.get('role','参考'))}：{t(a['description'])}" for a in refs)+"。")
        lines.extend(passages);lines += ["环境声："+sound,"画外配乐："+music]
    else:
        lines=[]
        if mode=="I2VA": lines.append("At 0.00 seconds, use <Picture 1> as the full opening frame of [Shot 1].\n")
        elif mode=="FL2VA": lines.append(f"Frame alignment: <Picture 1> anchors [Shot 1] at 0.00 seconds; <Picture 2> anchors [Shot {len(shots)}] at {total:.2f} seconds. Connect these states through the specified action.\n")
        elif mode=="L2VA": lines.append(f"Frame alignment: <Picture 1> anchors the end of [Shot {len(shots)}] at {total:.2f} seconds. Begin from the specified earlier state and converge to this frame.\n")
        if mode=="Ref2VA":
            definitions={}
            for a in refs:
                label=a["content_label"]
                definitions.setdefault(label,[]).append(f"{a['upload_label']} provides {a['role'].replace('_',' ')}: {t(a['description']).rstrip('.')}")
            lines.append("subject_definitions:\n"+"\n".join(f"{label}: "+"; ".join(items)+"." for label,items in definitions.items()))
            tasktypes=["reference generation"]
            if any(a['role'] in ('first_frame','last_frame') for a in refs): tasktypes.append("keyframe completion")
            if any(a['kind']=='audio' for a in refs): tasktypes.append("audio reuse" if any(a['role']=='audio_reuse' for a in refs) else "audio reference")
            lines.append(f"summary:\n[{' + '.join(tasktypes)}] A {total:g}-second {doc['project']['aspect_ratio']} video with {len(shots)} shot(s). "+" ".join(definitions.keys())+" retain the roles specified below.")
            retention=[]
            for label in definitions:
                group=[a for a in refs if a['content_label']==label]
                indices=[f"[Shot {i}]" for i,s in enumerate(shots,1) if any(s['shot_id'] in a['used_in_shots'] for a in group)]
                kind=group[0]["kind"]
                marker=group[0].get("retention", "reference" if kind=="audio" else ("weak_reference" if group[0]['role'] in ('style','camera_motion') else "fully_preserved"))
                retention.append(f"{label} (appears in {', '.join(indices)}): {marker} - Retain the defined reference role; follow the shot timeline for changing poses and framing.")
            lines.append("retention_analysis:\n"+"\n".join(retention))
            lines.append("detailed_description:\n"+style+"\n"+"\n".join(passages))
        else:
            passages[0]=passages[0].replace("[Shot 1] ","[Shot 1] "+style+" ",1)
            lines.append("integrated_multimodal_description:\n"+"\n".join(passages))
        lines += ["overall_soundscape:\n"+sound,"non_diegetic_music:\n"+music]
    prompt="\n\n".join(lines)+"\n"
    limit=char_limit if char_limit is not None else profile.get("max_prompt_chars")
    if limit is not None and (not isinstance(limit,int) or limit <= 0): raise ContractError("Prompt limit must be a positive integer")
    if limit is not None and len(prompt.rstrip("\n"))>limit:
        raise ContractError(f"Prompt has {len(prompt.rstrip(chr(10)))} Unicode characters; budget {limit}. Compress in the directing contract and review loss of meaning; the compiler never truncates.")
    manifest={"schema_version":VERSION,"profile_id":profile_id,"profile_sha256":digest(profile),"mode":mode,
        "requested_duration_sec":total,"aspect_ratio":doc["project"]["aspect_ratio"],"shot_ids":[s['shot_id'] for s in shots],
        "source_snapshot_sha256":digest(source) if source is not None else None,"source_snapshot_verified":source is not None,"contract_sha256":digest(doc),"prompt_sha256":digest(prompt.encode()),"prompt_char_count":len(prompt.rstrip("\n")),
        "upload_plan":refs,"missing_assets":missing,"speaker_map":speakers,
        "status":"draft_missing_assets" if missing else ("draft_offline" if draft else "compiled_offline_not_submitted"),
        "actual_model_id":None,"provider_payload":None,"submitted":False,"video_verified":False,
        "warnings":check['warnings']+([{'code':'SINGLE_JOB_MULTISHOT','where':profile_id,'message':'Multi-shot job retains explicit cuts. Confirm this grouping with the user and actual provider; it does not create new source shots.'}] if len(shots)>1 else [])+[{'code':'PROVIDER_PREFLIGHT','where':profile_id,'message':'This is a prompt bundle, not an API payload. Confirm actual provider/model/mode/limits/reference slots/rights and upload each asset; labels do not upload files.'}],
        "created_at":now()}
    return prompt,manifest
