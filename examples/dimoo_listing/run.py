#!/usr/bin/env python3
"""Run the DIMOO listing decision pipeline with JevHarness.

The pipeline asks Jev three independent questions about a product brief:
which main-image concept to lead with, which poster tone to use, and whether the
draft copy is grounded in confirmed evidence. Code then clamps the answers to
the allowed options and writes the decision record.

Usage:
  python examples/dimoo_listing/run.py --mock          # plumbing check, no API
  AI_GATEWAY_API_KEY=... python examples/dimoo_listing/run.py --transport vercel
  TYPESAFE_API_KEY=...   python examples/dimoo_listing/run.py --transport typesafe

  python examples/dimoo_listing/run.py --agent-answers examples/dimoo_listing/agent_judgments.json

--agent-answers replays judgments written by the coding agent in the Jev answer
shape. No model or API is called. Results are labelled "agent_authored", not Jev.

Mock answers are placeholders from a deterministic stub, not creative judgments.
Do not use them as the design decision.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from auto_jev.providers import JevClient  # noqa: E402
from auto_jev.runtime import PipelineRuntime  # noqa: E402


class AgentJudge:
    """Drop-in for JevClient.judge that replays agent-authored answers. No network."""

    def __init__(self, answers: dict):
        self.answers = {k: v for k, v in answers.items() if not k.startswith('_')}
        self.metadata = {'transport': 'agent_authored'}
        self.stats = {'calls': 0, 'cache_hits': 0, 'input_tokens': 0, 'output_tokens': 0,
                      'elapsed_ms': 0.0, 'cost_usd': 0.0, 'unpriced_calls': 0}

    def judge(self, state, questions, model=None):
        answers = {}
        for ident, question in questions.items():
            if ident not in self.answers:
                raise KeyError(f'no agent judgment for question {ident!r}')
            answer = dict(self.answers[ident])
            if answer.get('type') != question['type']:
                raise ValueError(f'judgment type mismatch for {ident!r}')
            answers[ident] = answer
        self.stats['calls'] += 1
        return {'answers': answers}


def load_inputs(directory: Path = HERE):
    spec = json.loads((directory / 'pipeline.json').read_text(encoding='utf-8'))
    brief = json.loads((directory / 'brief.json').read_text(encoding='utf-8'))
    return spec, brief


def decide(brief: dict, spec: dict, jev) -> dict:
    result = PipelineRuntime(spec, jev).run(brief)
    if isinstance(result, dict) and 'output' in result:
        return result['output']
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--transport', choices=('auto', 'vercel', 'typesafe'), default='auto')
    parser.add_argument('--mock', action='store_true', help='Use the deterministic mock client (no network).')
    parser.add_argument('--agent-answers', type=Path, help='Replay agent-authored judgments (no API).')
    parser.add_argument('--out', type=Path, default=HERE / 'decision.json')
    args = parser.parse_args(argv)

    spec, brief = load_inputs()
    if args.agent_answers:
        jev = AgentJudge(json.loads(args.agent_answers.read_text(encoding='utf-8')))
    else:
        jev = JevClient(mock=args.mock, transport=args.transport, cache_dir=HERE / '.jev-cache')
    output = decide(brief, spec, jev)
    record = {
        'pipeline': spec['name'],
        'jev_transport': jev.metadata.get('transport'),
        'mock': args.mock,
        'judgment_source': 'agent_authored' if args.agent_answers else ('mock' if args.mock else 'jev'),
        'decision': output,
        'jev_stats': jev.stats,
    }
    args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
