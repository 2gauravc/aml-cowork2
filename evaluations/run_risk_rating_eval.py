"""Run the CDD graph against the LangSmith risk-rating dataset.

Required environment variables:
    LANGSMITH_API_KEY

Optional environment variables:
    LANGSMITH_DATASET_ID  Override the dataset ID configured below.

Run from the repository root:
    python -m evaluations.run_risk_rating_eval
"""

import os
from uuid import uuid4

from langsmith import Client, evaluate
from langsmith.utils import LangSmithNotFoundError

from evaluations.risk_rating import risk_rating_exact_match
from src.agents.graph import build_cdd_graph


DEFAULT_DATASET_ID = "94655420-6226-41d7-9acb-19602fee1f24"
DATASET_ID = os.getenv("LANGSMITH_DATASET_ID", DEFAULT_DATASET_ID)

# Build the graph once. LangSmith calls ``target`` once for each dataset example.
graph = build_cdd_graph()


def target(inputs: dict) -> dict:
    """Execute the CDD graph for one LangSmith dataset example."""
    return graph.invoke(
        inputs,
        config={"configurable": {"thread_id": f"langsmith-eval-{uuid4()}"}},
    )


if __name__ == "__main__":
    try:
        Client().read_dataset(dataset_id=DATASET_ID)
    except LangSmithNotFoundError as exc:
        raise SystemExit(
            "LangSmith could not find dataset "
            f"{DATASET_ID}. Check that LANGSMITH_API_KEY belongs to the same "
            "LangSmith workspace as the dataset, then set LANGSMITH_DATASET_ID "
            "to the UUID shown in that dataset's URL."
        ) from exc

    evaluate(
        target,
        data=DATASET_ID,
        evaluators=[risk_rating_exact_match],
        experiment_prefix="risk-rating-baseline",
    )
