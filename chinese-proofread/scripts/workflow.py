#!/usr/bin/env python3
"""Deterministic file workflow for multi-agent proofreading. Standard library only."""

import argparse
from datetime import datetime
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import sys

import report
import provenance
import policy
import guidance
import names as name_tools


# Data protocol identifier is retained for existing artifacts; not the skill name or release version.
SCHEMA = "gongwen-proofread/3.0"
REFERENCES = Path(__file__).resolve().parent.parent / 'references'


def rule_catalog():
    catalog = report.load_json(REFERENCES / 'rule-catalog.json')
    report.require(isinstance(catalog, dict) and bool(catalog), '规则目录必须是非空对象')
    for rule_id, options in catalog.items():
        report.identifier(rule_id, 'rule_id')
        report.require(isinstance(options, dict) and type(options.get('requires_necessity')) is bool,
                       rule_id + ' 必须声明 requires_necessity 布尔值')
    return catalog


RULE_CATALOG = rule_catalog()
RULE_IDS = set(RULE_CATALOG)


def rules_sha():
    # Rules and role contracts may evolve without editing scheduling code.
    # A running job cannot silently mix old and new quality instructions.
    digest = hashlib.sha256()
    for name in guidance.all_sources():
        digest.update(name.encode('utf-8') + b'\0')
        digest.update((REFERENCES / name).read_bytes() + b'\0')
    digest.update(Path(guidance.__file__).read_bytes())
    return digest.hexdigest()


def sha(document):
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def dump(path, value, overwrite=False, inputs=()):
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    return report.write_output(str(path), content, overwrite, [str(p) for p in inputs])


def load(path):
    return report.load_json(path)


def ordered_units(document):
    units = report.document_units(document)
    return [dict(id=bid, text=item["text"], location=item["location"])
            for bid, item in units.items()]


def make_groups(units, target_chars, max_chars):
    report.require(target_chars > 0 and max_chars >= target_chars, "字符阈值必须满足 0 < target <= max")
    groups, current, size = [], [], 0
    for unit in units:
        length = len(unit["text"])
        if current and (size >= target_chars or size + length > max_chars):
            groups.append(current)
            current, size = [], 0
        current.append(unit)
        size += length
        if size >= max_chars:
            groups.append(current)
            current, size = [], 0
    if current:
        groups.append(current)
    return groups


def batch_command(args):
    document = load(args.document)
    provenance.verify(document)
    units = ordered_units(document)
    groups = make_groups(units, args.target_chars, args.max_chars)
    fingerprint = sha(document)
    outdir = Path(args.output_dir).resolve()
    batch_records = []
    offset = 0
    for index, group in enumerate(groups):
        batch_id = "batch-{:03d}".format(index + 1)
        before = units[max(0, offset - args.context_units):offset]
        last = offset + len(group) - 1
        after = units[last + 1:last + 1 + args.context_units]
        offset = last + 1
        payload = {
            "schema_version": SCHEMA,
            "task": "proofread-batch",
            "document_sha256": fingerprint,
            "rules_sha256": rules_sha(),
            "batch_id": batch_id,
            "title": document["title"],
            "source_name": document["source_name"],
            "main_units": group,
            "context_before": before,
            "context_after": after,
            "instructions": {
                "scope": "只检查 main_units；context 只帮助理解，不计入本批覆盖",
            },
        }
        target = outdir / (batch_id + ".json")
        dump(target, payload, args.overwrite, (args.document,))
        batch_records.append({
            "id": batch_id,
            "file": target.name,
            "main_unit_ids": [unit["id"] for unit in group],
            "main_chars": sum(len(unit["text"]) for unit in group),
            "input_sha256": sha(payload),
            "oversized_unit": len(group) == 1 and len(group[0]["text"]) > args.max_chars,
        })
    manifest = {
        "schema_version": SCHEMA,
        "task": "batch-manifest",
        "document_sha256": fingerprint,
        "rules_sha256": rules_sha(),
        "document_path": str(Path(args.document).resolve()),
        "target_chars": args.target_chars,
        "max_chars": args.max_chars,
        "context_units": args.context_units,
        "long_document": len(groups) > 1,
        "consistency_required": True,  # Every file workflow; independent of batching/delivery.
        "batches": batch_records,
    }
    dump(outdir / "manifest.json", manifest, args.overwrite, (args.document,))
    print("已生成 {} 个批次：{}".format(len(groups), outdir / "manifest.json"))
    if any(b["oversized_unit"] for b in batch_records):
        print("提示：存在超过 max_chars 的单个文字单元，已完整保留在单独批次中。")


def validate_manifest(document, manifest):
    provenance.verify(document)
    report.obj(manifest, "manifest")
    report.require(manifest.get("schema_version") == SCHEMA, "manifest 版本不匹配")
    report.require(manifest.get("task") == "batch-manifest", "manifest.task 无效")
    report.require(manifest.get("document_sha256") == sha(document), "manifest 与 document.json 不匹配")
    report.require(manifest.get("rules_sha256") == rules_sha(), "判定规则已变化，请创建新任务重查")
    batches = manifest.get("batches")
    report.require(isinstance(batches, list) and batches, "manifest.batches 必须非空")
    expected, seen, batch_ids = set(report.document_units(document)), [], set()
    for batch in batches:
        report.obj(batch, "manifest batch")
        report.identifier(batch.get("id"), "batch.id")
        report.require(batch['id'] not in batch_ids, '重复 batch.id')
        batch_ids.add(batch['id'])
        ids = report.strings(batch.get("main_unit_ids"), "batch.main_unit_ids")
        report.require(bool(ids) and len(ids) == len(set(ids)), "批次必须包含不重复的文字单元")
        seen.extend(ids)
    report.require(len(seen) == len(set(seen)), "批次主检查区出现重复文字单元")
    report.require(set(seen) == expected, "批次没有完整覆盖 document.json 的文字单元")
    return batches


def validate_anchor(units, anchor, label):
    report.obj(anchor, label)
    bid = report.identifier(anchor.get("block_id"), label + ".block_id")
    report.require(bid in units, label + " 引用了未知文字单元：" + bid)
    start, end = report.locate(units[bid]["text"], anchor, label)
    normalized = {"block_id": bid, "quote": anchor["quote"]}
    normalized["occurrence"] = anchor.get("occurrence", 1)
    return normalized, start, end


def validate_candidate(units, candidate, label, allowed_ids=None, pending_only=False):
    report.obj(candidate, label)
    local_id = report.identifier(candidate.get("id"), label + ".id")
    category = report.string(candidate.get("category"), label + ".category")
    reason = report.string(candidate.get("reason"), label + ".reason")
    severity = candidate.get("severity")
    rule_id = candidate.get("rule_id")
    report.require(rule_id in RULE_IDS, label + ".rule_id 无效")
    report.require(severity in ("confirmed", "pending"), label + ".severity 无效")
    if pending_only:
        report.require(severity == "pending", label + " 的一致性候选只能是 pending")
    anchors = candidate.get("anchors")
    report.require(isinstance(anchors, list) and anchors, label + ".anchors 必须非空")
    suggestion = candidate.get("suggestion")
    if severity == "confirmed":
        report.require(len(anchors) == 1, label + " 的明确错误只能有一个锚点")
        report.string(suggestion, label + ".suggestion", nonempty=False)
        report.require(suggestion != anchors[0].get("quote"), label + " 的修改前后相同")
    else:
        report.require(suggestion is None, label + " 的待核实项 suggestion 必须为 null")
    normalized, positions = [], []
    for index, anchor in enumerate(anchors):
        item, start, end = validate_anchor(units, anchor, label + ".anchors[{}]".format(index))
        if allowed_ids is not None:
            report.require(item["block_id"] in allowed_ids, label + " 的锚点不属于本批 main_units")
        normalized.append(item)
        positions.append((item["block_id"], start, end))
    return {"id": local_id, "category": category, "reason": reason, "severity": severity, "rule_id": rule_id,
            "anchors": normalized, "suggestion": suggestion}, positions


def validate_result(document, manifest, batch, pass_id, path):
    units = report.document_units(document)
    value = load(path)
    report.obj(value, str(path))
    report.require(value.get("schema_version") == SCHEMA, str(path) + " 版本不匹配")
    report.require(value.get("task") == "proofread-result", str(path) + " task 无效")
    report.require(value.get("document_sha256") == manifest["document_sha256"], str(path) + " 文档指纹不匹配")
    report.require(value.get("batch_id") == batch["id"], str(path) + " batch_id 不匹配")
    report.require(value.get("pass_id") == pass_id, str(path) + " pass_id 不匹配")
    report.require(value.get("rules_sha256") == manifest['rules_sha256'], "初检结果的规则版本不匹配")
    report.require(value.get("batch_input_sha256") == batch['input_sha256'], "初检结果的批次输入已过期")
    executor = value.get("executor")
    report.require(executor in ("subagent", "main-agent-fallback"), str(path) + ".executor 无效")
    limitations = report.strings(value.get("limitations"), str(path) + ".limitations")
    checked = report.strings(value.get("checked_unit_ids"), str(path) + ".checked_unit_ids")
    report.require(len(checked) == len(set(checked)), str(path) + " checked_unit_ids 重复")
    allowed = set(batch["main_unit_ids"])
    report.require(set(checked) <= allowed, str(path) + " 记录了本批之外的检查单元")
    candidates = value.get("candidates")
    report.require(isinstance(candidates, list), str(path) + ".candidates 必须是列表")
    result_candidates, local_ids = [], set()
    for index, candidate in enumerate(candidates):
        item, positions = validate_candidate(units, candidate, str(path) + ".candidates[{}]".format(index), allowed)
        report.require(item["id"] not in local_ids, str(path) + " 候选 id 重复")
        local_ids.add(item["id"])
        report.require(set(a["block_id"] for a in item["anchors"]) <= set(checked),
                       str(path) + " 候选引用了未标记完成的单元")
        item["positions"] = positions
        result_candidates.append(item)
    terms = value.get("terms")
    report.require(isinstance(terms, list), str(path) + ".terms 必须是列表")
    normalized_terms = []
    for index, term in enumerate(terms):
        label = str(path) + ".terms[{}]".format(index)
        report.obj(term, label)
        value_text = report.string(term.get("text"), label + ".text")
        kind = report.string(term.get("kind"), label + ".kind")
        bid = report.identifier(term.get("block_id"), label + ".block_id")
        report.require(bid in allowed and bid in set(checked), label + " 引用了未完成或非本批单元")
        report.require(value_text in units[bid]["text"], label + " 的名称不在原文中")
        normalized_terms.append({"text": value_text, "kind": kind, "block_id": bid})
    return checked, limitations, result_candidates, normalized_terms, executor


def confirmed_edit_signature(item, units):
    report.require(len(item.get("positions", [])) == 1, "明确错误缺少可计算的原文位置")
    block_id, start, end = item["positions"][0]
    # Compare the effect on the original unit. This also unifies deletion of
    # either copy of a repeated character/phrase, unlike anchor-span trimming.
    text = units[block_id]['text']
    effect = text[:start] + item['suggestion'] + text[end:]
    return block_id, hashlib.sha256(effect.encode('utf-8')).hexdigest()


def candidate_key(item, units):
    if item["severity"] == "confirmed":
        return "confirmed", confirmed_edit_signature(item, units)
    anchors = tuple((a["block_id"], a["quote"], a.get("occurrence"))
                    for a in item["anchors"])
    return "pending", anchors


def merge_candidates(items, units):
    merged = {}
    for item in items:
        key = candidate_key(item, units)
        if key not in merged:
            merged[key] = {k: v for k, v in item.items()
                           if k not in ("positions", "source", "conflict_group")}
            merged[key]["_positions"] = list(item.get("positions", []))
            merged[key]["sources"] = []
            merged[key]["reasons"] = []
        elif (item["severity"] == "confirmed"
              and len(item["anchors"][0]["quote"]) < len(merged[key]["anchors"][0]["quote"])):
            sources, reasons = merged[key]["sources"], merged[key]["reasons"]
            replacement = {k: v for k, v in item.items()
                           if k not in ("positions", "source", "conflict_group")}
            replacement["_positions"] = list(item.get("positions", []))
            replacement["sources"], replacement["reasons"] = sources, reasons
            merged[key] = replacement
        for source in item.get("sources", [item.get("source")]):
            if source and source not in merged[key]["sources"]:
                merged[key]["sources"].append(source)
        for reason in item.get("reasons", []) + [item["reason"]]:
            if reason not in merged[key]["reasons"]:
                merged[key]["reasons"].append(reason)
    candidates = list(merged.values())
    for index, item in enumerate(candidates, 1):
        item["id"] = "candidate-{:04d}".format(index)
    conflicts = {item["id"]: set() for item in candidates}
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1:]:
            if any(a_bid == b_bid and a_start < b_end and b_start < a_end
                   for a_bid, a_start, a_end in left["_positions"]
                   for b_bid, b_start, b_end in right["_positions"]):
                conflicts[left["id"]].update((left["id"], right["id"]))
                conflicts[right["id"]].update((left["id"], right["id"]))
    order = {item["id"]: index for index, item in enumerate(candidates)}
    for item in candidates:
        item["conflict_group"] = sorted(conflicts[item["id"]], key=order.get)
        item.pop("_positions", None)
    return candidates


def candidate_groups(document, candidates):
    """Connected components, including transitive overlaps, are indivisible."""
    by_id = {item["id"]: item for item in candidates}
    seen, groups = set(), []
    for candidate in candidates:
        if candidate["id"] in seen:
            continue
        todo, members = [candidate["id"]], set()
        while todo:
            cid = todo.pop()
            if cid in members:
                continue
            members.add(cid)
            todo.extend(by_id[cid]["conflict_group"])
        seen.update(members)
        selection = [item for item in candidates if item["id"] in members]
        context_ids = {unit["id"] for item in selection for unit in context_for(document, item)}
        groups.append({"id": "group-{:04d}".format(len(groups) + 1),
                       "candidates": selection,
                       "context_unit_ids": [unit["id"] for unit in ordered_units(document)
                                            if unit["id"] in context_ids]})
    return groups


def pack_groups(groups, max_candidates, max_chars=None, measure=None):
    report.require(max_candidates > 0, 'max_candidates 必须大于 0')
    report.require(max_chars is None or max_chars > 0, 'max_input_chars 必须大于 0')
    packs, current, size = [], [], 0
    for group in groups:
        count = len(group["candidates"])
        if current and (size + count > max_candidates or
                        (max_chars is not None and measure(current + [group]) > max_chars)):
            packs.append(current)
            current, size = [], 0
        current.append(group)
        size += count
    if current:
        packs.append(current)
    return packs


def term_index(units, terms):
    return name_tools.index(units, terms)


def merge_command(args):
    document, manifest = load(args.document), load(args.manifest)
    batches = validate_manifest(document, manifest)
    units = report.document_units(document)
    checked = {"A": set(), "B": set()}
    limitations, candidates, terms, executions = [], [], [], []
    results_dir = Path(args.results_dir).resolve()
    for batch in batches:
        for pass_id in ("A", "B"):
            path = results_dir / pass_id / (batch["id"] + ".json")
            if not path.is_file():
                limitations.append("缺少检查结果：{} {}".format(pass_id, batch["id"]))
                continue
            done, notes, found, names, executor = validate_result(document, manifest, batch, pass_id, path)
            checked[pass_id].update(done)
            limitations.extend("{} {}：{}".format(pass_id, batch["id"], note) for note in notes)
            executions.append({"pass_id": pass_id, "batch_id": batch["id"], "executor": executor,
                               "complete": set(done) == set(batch['main_unit_ids']),
                               "execution": load(path).get('execution', {})})
            if executor == "main-agent-fallback":
                limitations.append("{} {} 由主 Agent 补做，独立性降低".format(pass_id, batch["id"]))
            for item in found:
                item["source"] = "{}/{}".format(pass_id, batch["id"])
                candidates.append(item)
            terms.extend(names)
    merged_candidates = merge_candidates(candidates, units)
    merged = {
        "schema_version": SCHEMA, "task": "merged-candidates",
        "document_sha256": manifest["document_sha256"],
        "long_document": bool(manifest.get("long_document")),
        "consistency_required": policy.consistency_required(manifest),
        "executions": executions,
        "expected_batch_ids": [batch['id'] for batch in batches],
        "rules_sha256": manifest['rules_sha256'],
        "passes": [{"id": pid, "checked_block_ids": [bid for bid in units if bid in checked[pid]]} for pid in ("A", "B")],
        "limitations": limitations, "candidates": merged_candidates,
    }
    consistency = {
        "schema_version": SCHEMA, "task": "consistency-input",
        "document_sha256": manifest["document_sha256"], "required": policy.consistency_required(manifest),
        "title": document["title"], "source_name": document["source_name"],
        "terms": term_index(units, terms),
        "instructions": "仅比较同一对象可能存在的不同写法；返回具体原文锚点，不泛泛要求核实。",
    }
    consistency['blocks'] = name_tools.blocks(units, consistency['terms'])
    expected = [batch['id'] for batch in batches]
    consistency['coverage'], consistency['coverage_notes'] = name_tools.coverage(expected, executions)
    merged['limitations'].extend(consistency['coverage_notes'])
    dump(args.output, merged, args.overwrite, (args.document, args.manifest))
    consistency['max_input_chars'] = policy.CONSISTENCY_INPUT_CHARS
    consistency['merged_sha256'] = sha(merged)
    dump(args.consistency_output, consistency, args.overwrite, (args.document, args.manifest))
    print("已合并 {} 条候选；一致性索引包含 {} 个名称：{}".format(
        len(merged_candidates), len(consistency["terms"]), args.output))
    if limitations:
        print("提示：存在 {} 条检查限制或缺失记录。".format(len(limitations)))


def load_consistency(document, fingerprint, path, required, merged_sha256=None):
    if not path:
        return [], (["长文名称一致性检查未完成"] if required else [])
    value = load(path)
    report.obj(value, "consistency-result")
    report.require(value.get("schema_version") == SCHEMA, "consistency-result 版本不匹配")
    report.require(value.get("task") == "consistency-result", "consistency-result.task 无效")
    report.require(value.get("document_sha256") == fingerprint, "consistency-result 文档指纹不匹配")
    if merged_sha256 is not None:
        report.require(value.get('merged_sha256') == merged_sha256, '名称一致性结果对应旧候选或旧名称索引')
    report.require(value.get("checked") is True, "一致性检查未标记完成")
    notes = report.strings(value.get("limitations"), "consistency-result.limitations")
    candidates = value.get("candidates")
    report.require(isinstance(candidates, list), "consistency-result.candidates 必须是列表")
    units = report.document_units(document)
    normalized = []
    for index, candidate in enumerate(candidates):
        item, positions = validate_candidate(units, candidate, "consistency candidates[{}]".format(index), pending_only=True)
        item["positions"] = positions
        item["source"] = "consistency"
        normalized.append(item)
    return normalized, notes


def context_for(document, candidate):
    units = ordered_units(document)
    order = {unit["id"]: index for index, unit in enumerate(units)}
    wanted = set()
    for anchor in candidate["anchors"]:
        index = order[anchor["block_id"]]
        wanted.update(range(max(0, index - 1), min(len(units), index + 2)))
    return [units[index] for index in sorted(wanted)]


def review_view(groups):
    """Keep audit evidence in merged.json, not in the reviewer's decision input."""
    return [dict(group, candidates=[{key: value for key, value in candidate.items()
                                    if key not in ('reason', 'reasons', 'sources')}
                                   for candidate in group['candidates']]) for group in groups]


def candidate_statistics(merged):
    counts = dict(a_only=0, b_only=0, shared=0, other=0, total=0)
    for candidate in merged.get('candidates', []):
        passes = {source.split('/')[0] for source in candidate.get('sources', [])} & {'A', 'B'}
        name = 'shared' if len(passes) == 2 else ('a_only' if passes == {'A'} else 'b_only' if passes == {'B'} else 'other')
        counts[name] += 1
        counts['total'] += 1
    return counts


def execution_audit(merged):
    """Identifiers are execution declarations, never proof of unexposed context."""
    pairs = {}
    for row in merged.get('executions', []):
        pairs.setdefault(row['batch_id'], {})[row['pass_id']] = row
    expected = merged.get('expected_batch_ids', list(pairs))
    result = dict(batch_pairs=len(expected), completed_pairs=0, host_distinct_pairs=0,
                  declared_distinct_pairs=0, collision_pairs=0, unknown_pairs=0, fallback_pairs=0)
    for bid in expected:
        rows = [pairs.get(bid, {}).get(pid, {}) for pid in ('A', 'B')]
        result['completed_pairs'] += int(all(row.get('complete') is True for row in rows))
        if any(row.get('executor') == 'main-agent-fallback' for row in rows):
            result['fallback_pairs'] += 1
            continue
        records = [row.get('execution') or {} for row in rows]
        known = all(usable_execution(record) for record in records)
        if not known:
            result['unknown_pairs'] += 1
        elif records[0]['context_id'] == records[1]['context_id']:
            result['collision_pairs'] += 1
        elif all(record['context_source'] == 'host-provided' for record in records):
            result['host_distinct_pairs'] += 1
        else:
            result['declared_distinct_pairs'] += 1
    return result


def usable_execution(record):
    if not isinstance(record, dict) or record.get('context_source') not in ('host-provided', 'agent-declared'):
        return False
    if not all(isinstance(record.get(key), str) and record[key].strip()
               for key in ('context_id', 'ticket', 'opened_at', 'submitted_at')):
        return False
    try:
        start, end = [datetime.fromisoformat(record[key].replace('Z', '+00:00'))
                      for key in ('opened_at', 'submitted_at')]
        return start.tzinfo is not None and end.tzinfo is not None and start <= end
    except (ValueError, TypeError):
        return False


def review_plan_command(args):
    document, manifest, merged = load(args.document), load(args.manifest), load(args.merged)
    validate_manifest(document, manifest)
    report.require(merged.get("schema_version") == SCHEMA and merged.get("task") == "merged-candidates", "merged 文件无效")
    report.require(merged.get("document_sha256") == manifest["document_sha256"], "merged 与文档不匹配")
    local = merged.get("candidates")
    report.require(isinstance(local, list), "merged.candidates 必须是列表")
    consistency, consistency_notes = load_consistency(document, manifest["document_sha256"], args.consistency_result, policy.consistency_required(manifest), sha(merged))
    units = report.document_units(document)
    all_candidates = []
    local_ids = set()
    for index, item in enumerate(local):
        normalized, positions = validate_candidate(
            units, item, "merged.candidates[{}]".format(index))
        report.require(normalized["id"] not in local_ids, "merged.candidates 的 id 重复")
        local_ids.add(normalized["id"])
        sources = report.strings(item.get("sources"), "merged.candidates.sources")
        normalized["sources"] = sources
        normalized["positions"] = positions
        normalized["reasons"] = report.strings(
            item.get("reasons"), "merged.candidates.reasons")
        all_candidates.append(normalized)
    all_candidates.extend(consistency)
    combined = merge_candidates(all_candidates, units)
    for candidate in combined:
        candidate['requires_necessity'] = needs_necessity(candidate)
    outdir = Path(args.output_dir).resolve()
    batches = []
    max_chars = getattr(args, 'max_input_chars', policy.REVIEW_INPUT_CHARS)
    all_units, rule_fingerprint = ordered_units(document), rules_sha()
    def payload_for(selection, review_id='review-000'):
        context_ids = {bid for group in selection for bid in group["context_unit_ids"]}
        return {
            "schema_version": SCHEMA, "task": "review-batch",
            "document_sha256": manifest["document_sha256"], "review_batch_id": review_id,
            "rules_sha256": rule_fingerprint,
            "context_units": [unit for unit in all_units if unit["id"] in context_ids],
            "candidate_groups": review_view(selection),
            "instructions": "按本任务指引逐组裁决候选，保留正确发现、排除误改。初检理由、来源和票数已隐藏。每个候选决定一次，不扩展到组外问题。",
        }
    measure = lambda selection: len(json.dumps(payload_for(selection), ensure_ascii=False, indent=2)) + 1
    for selection in pack_groups(candidate_groups(document, combined), args.max_candidates, max_chars, measure):
        review_id = "review-{:03d}".format(len(batches) + 1)
        payload = payload_for(selection, review_id)
        input_chars = len(json.dumps(payload, ensure_ascii=False, indent=2)) + 1
        # An indivisible overlap group is never silently truncated or split.
        oversized = input_chars > max_chars
        dump(outdir / (review_id + ".json"), payload, args.overwrite, (args.document, args.merged))
        batches.append({"id": review_id, "file": review_id + ".json", "input_sha256": sha(payload),
                        "input_chars": input_chars, "budget_exceeded": oversized,
                        "groups": [{"id": group["id"], "candidate_ids": [c["id"] for c in group["candidates"]]}
                                   for group in selection]})
    plan = {
        "schema_version": SCHEMA, "task": "review-manifest", "document_sha256": manifest["document_sha256"],
        "merged_sha256": sha(merged),
        "rules_sha256": rules_sha(),
        "max_input_chars": max_chars,
        "batches": batches, "candidate_count": len(combined), "consistency_limitations": consistency_notes,
    }
    dump(outdir / "manifest.json", plan, args.overwrite, (args.document, args.merged))
    print("已生成 {} 个复核批次，共 {} 条候选：{}".format(len(batches), len(combined), outdir / "manifest.json"))


def review_decisions(document, payload, value):
    """A missing decision invalidates its entire connected group, never half a group."""
    units = report.document_units(document)
    groups = {g["id"]: g for g in payload["candidate_groups"]}
    answers = value.get("group_decisions")
    report.require(isinstance(answers, list), "group_decisions 必须是列表")
    seen, findings, notes = set(), [], []
    for answer in answers:
        report.obj(answer, "group_decision")
        gid = answer.get("group_id")
        report.require(isinstance(gid, str) and gid in groups and gid not in seen, "重复或未知 group_id")
        seen.add(gid)
        originals = {c["id"]: c for c in groups[gid]["candidates"]}
        touched, selected = set(), []
        necessity = report.obj(answer.get('necessity', {}), 'necessity')
        report.require(set(necessity) <= set(answer.get('accept', [])), 'necessity 只能对应本组 accept 的候选编号')
        explanations = report.obj(answer.get('explanations', {}), 'explanations')
        report.require(set(explanations) <= set(answer.get('accept', [])), 'explanations 只能对应本组 accept 的候选编号')

        def claim(cid):
            report.require(isinstance(cid, str) and cid in originals and cid not in touched,
                           gid + " 含重复或未知 candidate_id：" + str(cid))
            touched.add(cid)

        if "decisions" in answer:
            report.require(not any(k in answer for k in ("accept", "reject", "replace")), "复核格式不能混用")
            report.require(isinstance(answer["decisions"], list), "decisions 必须是列表")
            for decision in answer["decisions"]:
                report.obj(decision, "decision")
                cid = decision.get("candidate_id")
                claim(cid)
                finding = validate_decision(units, decision, cid, gid + "/" + cid)
                if finding:
                    finding["rule_id"] = decision.get("rule_id", originals[cid]["rule_id"])
                    report.require(finding["rule_id"] in RULE_IDS, "rule_id 无效")
                    finding['necessity'] = decision.get('necessity')
                    selected.append(finding)
        else:
            for cid in report.strings(answer.get("accept", []), "accept"):
                claim(cid)
                finding = dict(originals[cid])
                report.require(finding['severity'] == 'confirmed', '待核实意见请用 replace 写出复核后具体需要核对的问题')
                for field in ("id", "sources", "reasons", "conflict_group", "requires_necessity"):
                    finding.pop(field, None)
                mechanical = report.change_markup(finding['anchors'][0]['quote'], finding['suggestion'])[2]
                finding['reason'] = mechanical or report.string(explanations.get(cid),
                    cid + '.explanations：请用一个短句说明修改依据，不重复修改对照')
                finding["reviewed"] = True
                finding['necessity'] = necessity.get(cid)
                selected.append(finding)
            rejected = answer.get("reject", [])
            report.require(isinstance(rejected, list), "reject 必须是列表")
            for rejection in rejected:
                report.obj(rejection, "reject item")
                cid = rejection.get("id")
                claim(cid)
                code = rejection.get("code")
                report.require(code in ("valid-original", "duplicate", "insufficient-evidence", "protected-context", "out-of-scope"),
                               "reject.code 无效")
                report.require(not (originals[cid]["rule_id"] == "P-CN" and code == "out-of-scope"),
                               "中文标点规范属于默认范围，不能以纯风格为由剔除")
                report.string(rejection.get("reason"), "reject.reason")
            replacements = answer.get("replace", [])
            report.require(isinstance(replacements, list), "replace 必须是列表")
            for replacement in replacements:
                report.obj(replacement, "replace item")
                ids = report.strings(replacement.get("candidate_ids"), "replace.candidate_ids")
                report.require(bool(ids), "replace.candidate_ids 不能为空")
                for cid in ids:
                    claim(cid)
                report.string(replacement.get("reason"), "replace.reason")
                new_items = replacement.get("findings")
                report.require(isinstance(new_items, list), "replace.findings 必须是列表")
                for index, new_item in enumerate(new_items):
                    report.obj(new_item, "replace finding")
                    candidate, _ = validate_candidate(units, dict(new_item, id="replacement-" + str(index)), "replace finding")
                    candidate.pop("id")
                    candidate["reviewed"] = True
                    candidate['necessity'] = new_item.get('necessity')
                    selected.append(candidate)
        if touched != set(originals):
            notes.append("候选组未完整复核，整组暂不交付：" + gid)
            continue
        allowed_ids = {a["block_id"] for c in originals.values() for a in c["anchors"]}
        report.require(all(a["block_id"] in allowed_ids for f in selected for a in f["anchors"]),
                       gid + " 的复核意见越出候选所属文字单元")
        covered = {}
        for candidate in originals.values():
            for anchor in candidate['anchors']:
                _, start, end = validate_anchor(units, anchor, gid)
                covered.setdefault(anchor['block_id'], []).append((start, end))
        for bid, intervals in covered.items():
            union = []
            for start, end in sorted(intervals):
                if union and start <= union[-1][1]:
                    union[-1] = (union[-1][0], max(end, union[-1][1]))
                else:
                    union.append((start, end))
            covered[bid] = union
        for finding in selected:
            if needs_necessity(finding):
                report.string(finding.get('necessity'), gid + ' 的必要性依据 necessity')
            elif finding.get('necessity') is None:
                finding.pop('necessity', None)
            for anchor in finding['anchors']:
                _, start, end = validate_anchor(units, anchor, gid)
                report.require(any(left <= start and end <= right for left, right in covered[anchor['block_id']]),
                               gid + ' 的修改锚点越出本组范围，可能干扰其他复核组')
        check = {"method": "分组数据核验", "limitations": [],
                 "passes": [{"id": p, "checked_block_ids": list(units)} for p in ("A", "B")],
                 "findings": [dict(f, id="check-" + str(i)) for i, f in enumerate(selected)]}
        report.validate(document, check)
        findings.extend(selected)
    notes.extend("缺少候选组复核：" + gid for gid in groups if gid not in seen)
    return findings, notes


def needs_necessity(finding):
    if finding['severity'] != 'confirmed':
        return False
    if RULE_CATALOG[finding['rule_id']]['requires_necessity']:
        return True
    before, after = finding['anchors'][0]['quote'], finding['suggestion']
    for tag, left, right, begin, end in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        changed = before[left:right] + after[begin:end]
        if set(changed) & set('的地得'):
            return True
        if (tag in ('insert', 'delete') or right - left != end - begin) and any(c.isalnum() for c in changed):
            return True
    return False


def validate_decision(units, decision, candidate_id, label):
    report.obj(decision, label)
    report.require(decision.get("candidate_id") == candidate_id, label + " candidate_id 不匹配")
    outcome = decision.get("decision")
    report.require(outcome in ("confirmed", "pending", "reject"), label + ".decision 无效")
    reason = report.string(decision.get("reason"), label + ".reason")
    if outcome == "reject":
        return None
    category = report.string(decision.get("category"), label + ".category")
    anchors = decision.get("anchors")
    report.require(isinstance(anchors, list) and anchors, label + ".anchors 必须非空")
    normalized = [validate_anchor(units, anchor, label)[0] for anchor in anchors]
    suggestion = decision.get("suggestion")
    if outcome == "confirmed":
        report.require(len(normalized) == 1, label + " confirmed 只能有一个锚点")
        report.string(suggestion, label + ".suggestion", nonempty=False)
    else:
        report.require(suggestion is None, label + " pending 的 suggestion 必须为 null")
    return {"severity": outcome, "category": category, "reason": reason,
            "reviewed": True, "anchors": normalized, "suggestion": suggestion}


def finalize_command(args):
    document, merged, plan = load(args.document), load(args.merged), load(args.review_manifest)
    units = report.document_units(document)
    fingerprint = sha(document)
    provenance.verify(document)
    report.require(merged.get("document_sha256") == fingerprint, "merged 与文档不匹配")
    report.require(plan.get("schema_version") == SCHEMA and plan.get("task") == "review-manifest", "review manifest 无效")
    report.require(plan.get("document_sha256") == fingerprint, "review manifest 与文档不匹配")
    report.require(plan.get("merged_sha256") == sha(merged), "复核计划已过期，请重新生成")
    report.require(plan.get("rules_sha256") == merged.get('rules_sha256') == rules_sha(), '判定规则已变化，结果不可复用')
    results_dir = Path(args.review_results_dir).resolve()
    findings, limitations, final_id = [], list(merged.get("limitations", [])) + list(plan.get("consistency_limitations", [])), 0
    counts = dict(candidate_count=plan['candidate_count'], accepted=0, rejected=0, replaced=0, complete=True)
    for batch in plan.get("batches", []):
        path = results_dir / (batch["id"] + ".json")
        if not path.is_file():
            limitations.append(("复核输入超出预算，未检查：" if batch.get("budget_exceeded") else "缺少候选复核结果：") + batch["id"])
            counts['complete'] = False
            continue
        value = load(path)
        report.obj(value, str(path))
        report.require(value.get("schema_version") == SCHEMA and value.get("task") == "review-result", str(path) + " 类型无效")
        report.require(value.get("document_sha256") == fingerprint and value.get("review_batch_id") == batch["id"], str(path) + " 标识不匹配")
        payload = load(Path(args.review_manifest).resolve().parent / batch["file"])
        report.require(sha(payload) == batch["input_sha256"], "复核输入发生变化")
        report.require(value.get("review_input_sha256") == batch["input_sha256"], "复核结果已过期或对应其他输入")
        selected, notes = review_decisions(document, payload, value)
        if notes:
            counts['complete'] = False
        for answer in value['group_decisions']:
            if 'decisions' in answer:
                for decision in answer['decisions']:
                    counts['rejected' if decision['decision'] == 'reject' else 'accepted'] += 1
            else:
                counts['accepted'] += len(answer.get('accept', []))
                counts['rejected'] += len(answer.get('reject', []))
                counts['replaced'] += sum(len(item['candidate_ids']) for item in answer.get('replace', []))
        limitations.extend(notes)
        for finding in selected:
            final_id += 1
            finding["id"] = "finding-{:04d}".format(final_id)
            findings.append(finding)
        limitations.extend("{}：{}".format(batch["id"], note) for note in report.strings(value.get("limitations"), str(path) + ".limitations"))
    executions = merged.get("executions", [])
    fallback_count = sum(item.get("executor") == "main-agent-fallback"
                         for item in executions if isinstance(item, dict))
    if fallback_count:
        method = "按文件批次执行 A、B 两路检查；其中 {} 个批次结果由主 Agent 补做。".format(fallback_count)
    else:
        method = "按文件批次执行 A、B 两路检查；完成范围和执行上下文依据分别记录。"
    if policy.consistency_required(merged):
        method += "名称一致性检查状态见范围说明。"
    method += "报告中保留的意见均已按完整候选组及局部上下文复核。两路检查和复核可能共享模型盲区，不构成正确性保证。"
    if merged.get('names_only'):
        method = '仅复用既有名称采集数据，重新执行名称一致性检查及候选复核；本报告不包含原报告的其他修改。'
    audit = execution_audit(merged)
    if audit['collision_pairs']:
        limitations.append('发现 {} 个批次的 A/B 执行上下文标识相同，不满足隔离双检要求。'.format(audit['collision_pairs']))
    review = {
        "document_sha256": fingerprint,
        "names_only": bool(merged.get("names_only")),
        "method": method,
        "limitations": limitations,
        "passes": merged["passes"],
        "findings": findings,
        "execution_audit": audit,
        "process_statistics": {'initial_candidates': candidate_statistics(merged), 'review': counts},
    }
    report.validate(document, review)
    dump(args.output, review, args.overwrite, (args.document, args.merged, args.review_manifest))
    print("已形成最终结果：{} 条意见，{} 条限制：{}".format(len(findings), len(limitations), args.output))


def main():
    parser = argparse.ArgumentParser(description="中文文字校对文件化工作流，不调用模型或网络。")
    commands = parser.add_subparsers(dest="command", required=True)
    batch = commands.add_parser("batch", help="从 document.json 自动生成批次文件")
    batch.add_argument("--document", required=True)
    batch.add_argument("--output-dir", required=True)
    batch.add_argument("--target-chars", type=int, default=1600)
    batch.add_argument("--max-chars", type=int, default=2000)
    batch.add_argument("--context-units", type=int, default=1)
    batch.add_argument("--overwrite", action="store_true")
    merge = commands.add_parser("merge", help="验证并合并 A/B 检查结果")
    merge.add_argument("--document", required=True)
    merge.add_argument("--manifest", required=True)
    merge.add_argument("--results-dir", required=True)
    merge.add_argument("--output", required=True)
    merge.add_argument("--consistency-output", required=True)
    merge.add_argument("--overwrite", action="store_true")
    plan = commands.add_parser("review-plan", help="生成候选复核批次")
    plan.add_argument("--document", required=True)
    plan.add_argument("--manifest", required=True)
    plan.add_argument("--merged", required=True)
    plan.add_argument("--consistency-result")
    plan.add_argument("--output-dir", required=True)
    plan.add_argument("--max-candidates", type=int, default=25)
    plan.add_argument("--max-input-chars", type=int, default=policy.REVIEW_INPUT_CHARS)
    plan.add_argument("--overwrite", action="store_true")
    final = commands.add_parser("finalize", help="汇总复核结果为 review.json")
    final.add_argument("--document", required=True)
    final.add_argument("--merged", required=True)
    final.add_argument("--review-manifest", required=True)
    final.add_argument("--review-results-dir", required=True)
    final.add_argument("--output", required=True)
    final.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        report.require(getattr(args, "context_units", 0) >= 0, "context-units 不能为负数")
        report.require(getattr(args, "max_candidates", 1) > 0, "max-candidates 必须大于 0")
        if args.command == "batch":
            batch_command(args)
        elif args.command == "merge":
            merge_command(args)
        elif args.command == "review-plan":
            review_plan_command(args)
        else:
            finalize_command(args)
    except (ValueError, OSError, UnicodeError, LookupError) as exc:
        print("错误：" + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
