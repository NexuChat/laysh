# Laysh healed-module QA stage

Return only JSON matching the supplied QA schema. Do not use tools.

Review this healed candidate only. Approve it when it implements the fixed causal model, declared
outputs, and visible teaching evidence without adding forbidden capability. If a correction is
necessary, return the complete replacement module JavaScript; otherwise return null. Never return
HTML, reasoning, prompts, raw learner input, or extra fields.

QA_INPUT_JSON:
@@INPUT_JSON@@
