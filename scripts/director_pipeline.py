#!/usr/bin/env python3
"""Offline CLI for jingstudio. Python 3.10+. No provider calls."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from director_core import (ROOT, VERSION, ContractError, compiler, group_boards, ingest,
                           load_json, skeleton, validate, write_json, write_text)
from director_render import render_html, render_png, frame_jobs, continuity_graph


def outputs_available(paths, overwrite=False):
    if not overwrite:
        existing=[str(p) for p in paths if Path(p).exists()]
        if existing: raise ContractError("Refusing to overwrite existing artifacts: "+", ".join(existing))


def protect_inputs(outputs, inputs):
    """Explicit overwrite never authorizes replacing a command input."""
    for out in outputs:
        if not out: continue
        target=Path(out)
        for source in inputs:
            if not source: continue
            original=Path(source)
            if target.resolve()==original.resolve() or (target.exists() and original.exists() and target.samefile(original)):
                raise ContractError("Output would overwrite an input: "+str(target))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version",action="version",version=f"jingstudio {(ROOT / 'VERSION').read_text(encoding='utf-8').strip()} (contract schema {VERSION})")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("ingest",help="Read original XLSX/CSV/JSON rows without changing them")
    p.add_argument("input");p.add_argument("--out",required=True);p.add_argument("--project-name")
    p.add_argument("--sheet");p.add_argument("--header-row",type=int);p.add_argument("--overwrite",action="store_true")
    p=sub.add_parser("export-xlsx",help="Export original source rows to deterministic XLSX and verify roundtrip")
    p.add_argument("source");p.add_argument("--out",required=True);p.add_argument("--report",required=True)
    p.add_argument("--sheet",default="分镜表");p.add_argument("--overwrite",action="store_true")
    p=sub.add_parser("init",help="Create UNRESOLVED director draft; agent must design it")
    p.add_argument("source");p.add_argument("--out",required=True);p.add_argument("--overwrite",action="store_true")
    p=sub.add_parser("validate",help="Explicit-field checks, not image/video/aesthetic certification")
    p.add_argument("contract");p.add_argument("--stage",choices=["plan","production"],default="plan")
    p.add_argument("--asset-root");p.add_argument("--source",help="Independent preserved source JSON baseline (required for production; keep outside editable contract)")
    p.add_argument("--schema",action="store_true",help="Also use optional jsonschema package")
    p.add_argument("--out");p.add_argument("--overwrite",action="store_true")
    p=sub.add_parser("group",help="Plan review boards <=15s; no automatic shot recutting")
    p.add_argument("contract");p.add_argument("--out",required=True);p.add_argument("--overwrite",action="store_true")
    p.add_argument("--pagination",choices=["legacy","no-cut"],default="legacy")
    p.add_argument("--windows",help="Explicit no-cut review windows JSON, not production cuts")
    p=sub.add_parser("compile",help="Compile one model prompt bundle, never submit or generate")
    p.add_argument("contract");p.add_argument("--profile",required=True,choices=["seedance-2.0","seedance-2.5","minimax-h3"])
    p.add_argument("--mode",required=True);p.add_argument("--asset-root",required=True)
    p.add_argument("--source",help="Independent preserved source JSON with reviewed dialogue baseline; required unless --draft (still offline, never submits)")
    p.add_argument("--shot-ids",nargs="+");p.add_argument("--out-dir",required=True)
    p.add_argument("--draft",action="store_true");p.add_argument("--char-limit",type=int)
    p.add_argument("--overwrite",action="store_true")
    p=sub.add_parser("render",help="Compose a human review HTML/optional PNG; does not generate frames")
    p.add_argument("contract");p.add_argument("--asset-root",required=True);p.add_argument("--out")
    p.add_argument("--layout",choices=["review","design-board"],default="review")
    p.add_argument("--out-dir");p.add_argument("--review-plan");p.add_argument("--design-spec")
    p.add_argument("--require-blocking",action="store_true",help="Require complete hash-bound scene and per-shot spatial diagrams")
    p.add_argument("--format",choices=["html","png","both"],default="html")
    p.add_argument("--font",help="Local CJK font for PNG only; font is not redistributed")
    p.add_argument("--overwrite",action="store_true")
    p=sub.add_parser("frame-jobs",help="Write image-generation job plans with actual reference existence checks")
    p.add_argument("contract");p.add_argument("--asset-root",required=True);p.add_argument("--out",required=True)
    p.add_argument("--overwrite",action="store_true")
    p=sub.add_parser("continuity",help="Export explicit neighboring-shot state graph")
    p.add_argument("contract");p.add_argument("--out",required=True);p.add_argument("--overwrite",action="store_true")
    args=parser.parse_args(argv)
    try:
        input_paths=[getattr(args,k,None) for k in ("input","source","contract","windows","review_plan","design_spec")]
        output_paths=[getattr(args,k,None) for k in ("out","report")]
        if args.command=="compile": output_paths += [Path(args.out_dir)/"prompt.txt",Path(args.out_dir)/"manifest.json"]
        protect_inputs(output_paths,input_paths)
        if args.command=="ingest":
            data=ingest(args.input,args.project_name,args.sheet,args.header_row)
            write_json(args.out,data,args.overwrite)
            print(f"Imported {data['shot_count']} shots / {data['total_duration_sec']:g}s -> {args.out}")
        elif args.command=="export-xlsx":
            from director_export import export_xlsx
            report=export_xlsx(args.source,args.out,args.report,sheet_name=args.sheet,overwrite=args.overwrite)
            print(json.dumps(report,ensure_ascii=False,indent=2))
        elif args.command=="init":
            data=skeleton(load_json(args.source));write_json(args.out,data,args.overwrite)
            print(f"Created director DRAFT with {len(data['shots'])} shots; this is not a completed directing plan -> {args.out}")
        elif args.command=="validate":
            data=load_json(args.contract)
            source=load_json(args.source) if args.source else None
            report=validate(data,args.stage,args.asset_root,source=source)
            if args.schema:
                try: from jsonschema import Draft202012Validator
                except ImportError: raise ContractError("Full schema check requires optional dependency: python -m pip install jsonschema")
                validator=Draft202012Validator(load_json(ROOT/'schemas/director-contract.schema.json'))
                for error in validator.iter_errors(data):
                    report['errors'].append({'code':'JSON_SCHEMA','where':'.'.join(map(str,error.absolute_path)),'message':error.message});report['ok']=False
                report['json_schema_checked']=True
            if args.out: write_json(args.out,report,args.overwrite)
            print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report['ok'] else 2
        elif args.command=="group":
            data=load_json(args.contract)
            if args.pagination=="no-cut":
                from director_review_plan import plan_review
                plan=plan_review(data,load_json(args.windows) if args.windows else None)
            else:
                if args.windows: raise ContractError("--windows requires --pagination no-cut")
                plan=group_boards(data)
            write_json(args.out,plan,args.overwrite);print(args.out)
        elif args.command=="compile":
            out=Path(args.out_dir);paths=[out/'prompt.txt',out/'manifest.json']
            outputs_available(paths,args.overwrite)
            prompt,manifest=compiler(load_json(args.contract),args.profile,args.mode,args.asset_root,args.shot_ids,args.draft,args.char_limit,
                                     source=load_json(args.source) if args.source else None)
            write_text(paths[0],prompt,args.overwrite);write_json(paths[1],manifest,args.overwrite)
            print(f"{manifest['status']} / {manifest['prompt_char_count']} chars -> {out}")
        elif args.command=="render":
            data=load_json(args.contract)
            if args.layout=="design-board":
                if not args.out_dir or args.out: raise ContractError("design-board requires --out-dir, not --out")
                from director_design_board import render_design_board
                report=render_design_board(data,args.asset_root,args.out_dir,
                    review_plan=load_json(args.review_plan) if args.review_plan else None,
                    design_spec=load_json(args.design_spec) if args.design_spec else None,
                    format=args.format,font_path=args.font,overwrite=args.overwrite,
                    protected_paths=tuple(p for p in (args.contract,args.review_plan,args.design_spec) if p),require_blocking=args.require_blocking)
                print(json.dumps(report,ensure_ascii=False,indent=2));return 0
            if not args.out: raise ContractError("review layout requires --out")
            if args.out_dir or args.review_plan or args.design_spec or args.require_blocking: raise ContractError("Design-board options require --layout design-board")
            media_paths=[Path(args.asset_root)/a['path'] for a in data['assets'] if a.get('path')]
            media_paths += [Path(args.asset_root)/k['image_path'] for shot in data['shots'] for k in shot['keyframes'] if k.get('image_path')]
            protect_inputs([args.out],media_paths)
            outputs_available([args.out],args.overwrite)
            if Path(args.out).suffix.lower()=='.png': render_png(data,args.asset_root,args.out,args.font,args.overwrite)
            elif Path(args.out).suffix.lower() in ('.html','.htm'): write_text(args.out,render_html(data,args.asset_root),args.overwrite)
            else: raise ContractError("Review renderer supports .html or .png; not video, PDF, or image generation")
            print(f"Human review composition only -> {args.out}")
        elif args.command=="frame-jobs":
            write_json(args.out,frame_jobs(load_json(args.contract),args.asset_root),args.overwrite);print(args.out)
        elif args.command=="continuity":
            write_json(args.out,continuity_graph(load_json(args.contract)),args.overwrite);print(args.out)
        return 0
    except (ContractError,OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error:
        print(f"ERROR: {error}",file=sys.stderr);return 2

if __name__=="__main__":
    sys.exit(main())
