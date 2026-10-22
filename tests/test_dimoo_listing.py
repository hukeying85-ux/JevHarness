import json
from pathlib import Path

from auto_jev.spec import validate_spec
from auto_jev.runtime import PipelineRuntime
from auto_jev.providers import JevClient

ROOT = Path(__file__).resolve().parents[1] / 'examples' / 'dimoo_listing'


def test_dimoo_spec_is_valid_and_runs_in_mock_mode(tmp_path):
    spec = json.loads((ROOT / 'pipeline.json').read_text(encoding='utf-8'))
    brief = json.loads((ROOT / 'brief.json').read_text(encoding='utf-8'))
    validate_spec(spec)
    jev = JevClient(mock=True, transport='typesafe', cache_dir=tmp_path)
    result = PipelineRuntime(spec, jev).run(brief)
    output = result['output'] if isinstance(result, dict) and 'output' in result else result
    assert output['hero'] in {'character_hero', 'unboxing_surprise', 'collection_shelf', 'gift_scene'}
    assert output['tone'] in {'dreamy_pastel', 'night_glow', 'playful_pop'}
    assert output['copy_mode'] in {'confirmed_only', 'neutral_placeholder'}
    assert output['pending_claims_on_page'] is False
