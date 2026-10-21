"""Build one auditable Open WebUI tool from tested research sources.

Designed for the existing production v0.12.3 container. Importing this file
does not make API calls, register tools, modify WebUI or invoke a broker.
"""
from __future__ import annotations
import ast
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
COMPONENTS=(
    "quote_economics.py",
    "momentum_features.py",
    "finmem_research.py",
    "evidence_review.py",
    "market_gateway_normalizer.py",
    "research_context.py",
    "trading_brain_research_tool.py",
)
SKIP_MODULES={
    "quote_economics","momentum_features","finmem_research",
    "evidence_review","market_gateway_normalizer","research_context",
}
HEADER='''"""
title: Trading Brain Research Context
author: Trading Operations Engineering
description: Additive evidence, quote economics, market momentum, and optional prior research context. Never submits orders or changes broker settings.
version: 0.1.0
"""
from __future__ import annotations
'''

def generate() -> str:
    parts=[HEADER.rstrip()]
    for name in COMPONENTS:
        f=HERE/name
        tree=ast.parse(f.read_text(encoding="utf-8"),filename=str(f))
        nodes=[]
        for node in tree.body:
            if isinstance(node,ast.ImportFrom) and node.module=="__future__":
                continue
            if isinstance(node,ast.ImportFrom) and node.module in SKIP_MODULES:
                continue
            if isinstance(node,ast.If) and isinstance(node.test,ast.Compare):
                # No main/CLI execution is allowed in a WebUI loaded tool.
                if isinstance(node.test.left,ast.Name) and node.test.left.id=="__name__":
                    raise ValueError("Executable __main__ block in "+name)
            nodes.append(node)
        if not nodes:
            raise ValueError("Empty source "+name)
        parts.append("\n# ========== "+name+" ==========\n")
        parts.append(ast.unparse(ast.Module(body=nodes,type_ignores=[])))
    out="\n\n".join(parts)+"\n"
    compile(out,"<trading_brain_bundle>","exec")
    if len(out)>110_000:
        raise ValueError("Unexpected bundled tool size")
    if out.count("class Tools:")!=1:
        raise ValueError("Expected exactly one WebUI Tools class")
    for forbidden in ("place_market_order","import httpx","import requests"):
        if forbidden in out:
            raise ValueError("Unexpected broker/network code: "+forbidden)
    return out

def main():
    destination=Path(sys.argv[1]) if len(sys.argv)>1 else HERE/"trading_brain_webui_bundle.py"
    contents=generate()
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(contents,encoding="utf-8")
    print("TRADING_BRAIN_STANDALONE_TOOL_BUNDLE_PASS",
          "bytes",len(contents.encode("utf-8")),
          "file",str(destination))

if __name__=="__main__":
    main()
