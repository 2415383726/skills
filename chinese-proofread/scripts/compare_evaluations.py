#!/usr/bin/env python3
"""Compare paired, externally executed experiments. Never generates predictions."""
import argparse
import json
from pathlib import Path
import statistics
import sys

import evaluate
import report

VARIANTS = ('no-skill', 'single-pass', 'single-review', 'dual-review')


def compare(manifest_path):
    path = Path(manifest_path).resolve()
    manifest = report.load_json(path)
    report.string(manifest.get('model_config'), 'model_config（包含模型、推理配置及采样设置）')
    rows = manifest.get('runs')
    report.require(isinstance(rows, list) and rows, 'runs 必须是非空列表')
    pairs, scores = {}, {name: [] for name in VARIANTS}
    sources = set()
    for row in rows:
        variant = row.get('variant')
        report.require(variant in VARIANTS, 'variant 无效')
        material = report.string(row.get('material'), 'material')
        repeat = row.get('repeat')
        report.require(type(repeat) is int and repeat > 0, 'repeat 必须是正整数')
        report.require(type(row.get('delivered')) is bool, 'delivered 必须为布尔值')
        elapsed = row.get('elapsed_seconds')
        report.require(elapsed is None or (type(elapsed) in (int, float) and 0 <= elapsed < float('inf')), 'elapsed_seconds 无效')
        group = pairs.setdefault((material, repeat), {})
        report.require(variant not in group, '同一材料/轮次/模式重复')
        score = None
        if row.get('score_path'):
            source = (path.parent / row['score_path']).resolve()
            report.require(source not in sources, '不同实验不能复用同一评分文件')
            sources.add(source)
            score = report.load_json(source)
            for key in ('document_sha256', 'gold_sha256'):
                report.string(score.get(key), key)
            report.require(score.get('annotation_status') in evaluate.STATUSES, '标注状态无效')
            counts = score.get('overall', {})
            report.require(all(type(counts.get(k)) is int and counts[k] >= 0 for k in ('tp','fp','fn')), '评分计数无效')
        report.require(not row['delivered'] or score is not None, '已交付的实验必须提供实际评分')
        group[variant] = score
        scores[variant].append((row, score))
    for group in pairs.values():
        report.require(set(group) == set(VARIANTS), '每组必须记录四种模式，失败也应记录 delivered=false')
    # A named material must use identical source extraction and gold across repeats.
    bindings = {}
    for (material, _), group in pairs.items():
        for score in group.values():
            if score is not None:
                binding = (score['document_sha256'], score['gold_sha256'])
                report.require(material not in bindings or bindings[material] == binding, '同一材料的文档或金标不一致')
                bindings[material] = binding
    paired = [group for group in pairs.values() if all(group.values())]
    output = {}
    for variant, entries in scores.items():
        complete_scores = [group[variant] for group in paired]
        tp, fp, fn = [sum(s['overall'][key] for s in complete_scores) for key in ('tp','fp','fn')]
        elapsed = [r['elapsed_seconds'] for r, _ in entries if r.get('elapsed_seconds') is not None]
        output[variant] = dict(evaluate.metrics(tp, fp, fn),
            scored_pairs=len(paired), runs=len(entries),
            delivery_rate=sum(r['delivered'] for r, _ in entries)/len(entries),
            mean_elapsed_seconds=statistics.mean(elapsed) if len(elapsed)==len(entries) else None,
            no_change_false_positives=sum(s['no_change_false_positives'] for s in complete_scores))
    return {'model_config': manifest['model_config'], 'variants': output,
            'annotation_status': 'human-reviewed' if paired and all(s['annotation_status']=='human-reviewed' for g in paired for s in g.values()) else 'seed-unreviewed',
            'paired_groups': len(pairs), 'fully_scored_groups': len(paired),
            'limitations': ['修改质量只比较四种模式均有评分的配对组；未评分失败不冒充零错误，另计交付率。',
                            '失败未评分可能造成幸存者偏差，须结合交付率解读；耗时缺项时均值为 null。',
                            '模型配置与实际耗时由执行方记录；本工具不能证明人工审定、上下文隔离或运行真实性。']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = compare(args.manifest)
        report.write_output(args.output, json.dumps(result, ensure_ascii=False, indent=2)+'\n', False, [args.manifest])
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('错误：'+str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
