## 2026-11-12: measurement change, execution (measurement version 11 to 12) (eval-web; web search with the maintainer's Exa key)

Web search of the opencode adapter uses the maintainer's Exa key; the free endpoint answered 429 to every search.

- Kind: execution side: an adapter's environment changed. The measurement version is raised and an epoch is entered: for the skills and models it reaches, earlier lab lines are inherited evidence and the baselines expire.
- Epoch 2026-11-12: skills biz-business-model, biz-gtm, biz-icp-positioning, biz-market-analysis, brand-identity, brand-name, brand-strategy, core-research, eng-architecture (the keys of `web_cases`); models openrouter/deepseek/deepseek-v4.1-flash, openrouter/openai/gpt-6-luna.
- Fingerprint: `bda6ad390f116cbd92feb5b967c9277fb8afbeb709a5c70f06312cb3be1f212e`.
- Written by `python3 evals/eval_status.py measurement --kind execution`.
- What changed: `adapters/agents-dir/adapter.json` registers the secret `EXA_API_KEY` (store username `EXA_API_KEY`, metered, low limit); the two OpenRouter model entries of `evals/eval-gate.json` gain `"web_pass_env": ["OPENROUTER_API_KEY", "EXA_API_KEY"]`, so the key reaches a run only on a web case. `run-prompt.sh` is unchanged: opencode 1.19.4 reads `EXA_API_KEY` from its environment when `OPENCODE_ENABLE_EXA=1`, which the script already sets. The list repeats `OPENROUTER_API_KEY` because `web_pass_env` replaces `pass_env` on a web case and the key proxy still holds the model's key.
- Why: every web search of the last tests returned HTTP 429 from Exa's free endpoint, so a web case measured the skill's degraded mode. A scratch trial of one case after the change made 12 searches with no error and no 429.
- Cost to safety: the Exa key is in the run's environment (opencode puts it in the query of its search URL), unlike the model's key. A run on the open network could print it; a leak costs at most the key's spend limit. The maintainer approved this.
- Package id: `eval-web` was used because the task named no package id.
