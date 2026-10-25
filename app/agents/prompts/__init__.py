"""
app.agents.prompts
===================
Prompt templates, grouped one module per agent. Every prompt-building
function returns a `(system_prompt, user_prompt)` tuple and instructs
the model to respond in strict JSON when structured output is needed —
never free text that then gets regex-parsed. Keeping prompts in their
own module (not inlined in the agent file) means they can be
version-controlled, reviewed, and tuned independently of the agent's
control flow, and reused by other agents that need the same kind of
reasoning (e.g. a future AR agent reusing the duplicate-detection
narrative pattern).
"""
