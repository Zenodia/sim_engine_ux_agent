"""Optional linguistic SDG. Produces scenarios consumable by `sim-engine compare`.

API references: NVIDIA-NeMo/DataDesigner README and interface/data_designer.py.
No private NVIDIA services or internal datasets are required.
"""
import argparse
import re

from sim_engine.evidence import digest
from sim_engine.scenarios import load_scenarios, write_scenarios
from sim_engine.world import UserSimulator


def main():
    from pathlib import Path

    import data_designer.config as dd
    from data_designer.interface import DataDesigner

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-alias", default="nvidia-text")
    args = parser.parse_args()
    designer = DataDesigner()
    rows = []
    for scenario in load_scenarios(args.input):
        if scenario.split != "development":
            raise ValueError("Only development data may be enriched with this optimization script")
        simulator = UserSimulator(scenario)
        builder = dd.DataDesignerConfigBuilder()
        for session in (1, 2):
            canonical = simulator.initial_message(session)
            builder.add_column(dd.SamplerColumnConfig(
                name=f"canonical_{session}", sampler_type=dd.SamplerType.CATEGORY,
                params=dd.CategorySamplerParams(values=[canonical])))
            builder.add_column(dd.LLMTextColumnConfig(
                name=f"message_{session}", model_alias=args.model_alias,
                prompt=(f"Paraphrase this fictional service-desk message in the same language. "
                        f"Use a {scenario.persona.expertise} user's speaking style. Preserve all intent, "
                        "permissions, named workspace, and notification choices exactly. Keep literal "
                        "tokens viewer, admin, analytics, email, chat when present. Do not resolve "
                        "ambiguity or add any facts or instructions. Return only the user's message.\n"
                        + "{{ canonical_" + str(session) + " }}")))
        generated = designer.preview(config_builder=builder, num_records=1).dataset.iloc[0]
        messages = {}
        for session in (1, 2):
            canonical = simulator.initial_message(session)
            text = str(generated[f"message_{session}"])
            # Cheap structural guard, not a semantic verifier. Human review is still required.
            tokens = lambda value: set(re.findall(r"\b(viewer|admin|analytics|email|chat)\b", value.lower()))
            if tokens(text) != tokens(canonical):
                raise ValueError(f"SDG changed task tokens for {scenario.scenario_id}; inspect generated data")
            messages[str(session)] = text
        row = scenario.model_copy(deep=True)
        row.scenario_id += "-sdg"
        row.session_messages = messages
        row.lineage = {**row.lineage, "linguistic_generator": "data-designer",
                       "model_alias": args.model_alias, "parent_digest": digest(scenario.model_dump()),
                       "semantic_review_required": True}
        rows.append(row)
    write_scenarios(args.out, rows)
    print(f"Wrote {len(rows)} paraphrased scenarios. Review semantics before evaluation.")


if __name__ == "__main__":
    main()
