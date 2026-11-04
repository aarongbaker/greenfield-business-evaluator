# Comparing several ideas

When you have evaluated more than one idea, `greenfield portfolio` ranks them for what to test next. It re-scores each idea's `evaluation.json` itself, so a hand-edited `decision.json` cannot move an idea up the list.

## The manifest

Copy the template next to your research folders and fill it in. Its `_help` keys say what each block needs.

```bash
greenfield install --platform both --gitignore
cp .claude/skills/greenfield-business-evaluator/assets/portfolio-template.json portfolio.json
```

For each idea you supply:

- `evaluation`: the path to its `evaluation.json`, relative to the manifest. An optional `decision` that disagrees with the re-score leaves the idea unranked.
- `founder_fit_0_to_5` with a written rationale.
- `build`: cash and engineering weeks for a first version.
- `experiment`: the next falsifiable test, its pass/fail line set in advance, its cost, weeks and expected learning from 0 to 5.
- `forecast` (optional): low, base and high cases, each with buyers, 12-month revenue per buyer, variable cost per buyer and fixed cost.

`constraints` sets the total cash and engineering weeks you can spend across all ideas.

## Run it

```bash
greenfield portfolio portfolio.json --output portfolio-ranking.json --markdown PORTFOLIO.md  # needs-research
```

Run on the unfilled template, it lists every placeholder still left and exits 2, so nothing is ranked on made-up inputs.

## Reading the ranking

- The **priority index** is a heuristic, shown under three weightings: `balanced`, `capital_constrained` (cash and weeks matter more) and `learning_first` (the cheapest decisive experiment matters more). If the order changes between them, the choice depends on what you value.
- **No go** and **Research incomplete** ideas are never ranked to build. The Markdown table has a "Why unranked" column for every idea left out.
- **Forecasts** are plain arithmetic on the numbers you gave. Nothing is inferred about customers, churn or margins.

The index is not a probability, a valuation or investment advice. It tells you which experiment to run next, not which company to start.
