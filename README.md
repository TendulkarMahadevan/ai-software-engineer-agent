# 🤖 AI Software Engineer Agent

An autonomous AI agent that analyzes GitHub issues, locates relevant code, generates patches, validates changes through tests, and prepares pull request descriptions.

This project explores automated code repair using LLMs with strong safety guardrails, local repository reasoning, and test-based validation.

---

## 🚀 Overview

The AI Software Engineer Agent performs the following workflow:

1. Fetches a GitHub issue
2. Analyzes issue type (inbound/outbound, routing, UI, logic, etc.)
3. Clones repository locally
4. Runs baseline tests
5. Searches and ranks relevant files
6. Injects multi-file context (mini-RAG style)
7. Rewrites target file using LLM
8. Validates diff safety
9. Runs tests again
10. Generates PR description if safe and valid

The system is built to emphasize:
- Controlled modifications
- Test-based validation
- Prevention of unsafe large rewrites
- Multi-file contextual reasoning

---

## 🏗 Architecture

### Core Components

```

agent/
code_agent.py
keyword_extractor.py

tools/
github_tool.py
repo_search_tool.py
context_extractor.py

patch/
patch_generator.py
pr_writer.py

utils/
git_manager.py
diff_validator.py

llm/
openai_client.py

````

---

## 🧠 Key Features

### 1️⃣ Baseline Test Detection

Before modifying any code:

```python
baseline_test = run_tests()
````

If baseline tests are already failing, the agent logs the failure and continues in analysis mode.

---

### 2️⃣ Intelligent File Ranking

Files are ranked using keyword scoring:

* Boost inbound/routing signals
* Penalize outbound/send-only files
* Penalize very large files
* Dynamic scoring based on issue type

```python
if any(x in lower for x in ["handler", "dispatch", "listener"]):
    score += 6
```

---

### 3️⃣ Multi-File Context Injection (Mini-RAG)

Instead of modifying a file blindly:

* Top ranked file is selected
* Related files are injected into LLM prompt
* Context improves reasoning

```python
[AI-ENGINEER] Injecting 2 related files for context.
```

---

### 4️⃣ Diff Safety Guard

Prevents catastrophic rewrites.

If diff is:

* Too small → trivial change warning
* Too large → abort to prevent unsafe refactor

```python
if len(diff_output.splitlines()) > MAX_THRESHOLD:
    abort()
```

This prevents full file rewrites and hallucinated refactors.

---

### 5️⃣ Automated Test Validation

After rewriting:

* Tests are executed
* If failing → retry once
* If still failing → abort PR generation

---

### 6️⃣ Structured PR Generation

If:

* Diff is safe
* Tests pass
* Change is meaningful

Agent generates structured PR:

* Summary
* Why change needed
* What modified
* Test status

---

## 🔍 Current Capabilities

✔ GitHub issue ingestion
✔ Local repo cloning
✔ Branch creation
✔ Keyword-driven search
✔ Multi-file context injection
✔ Safe patch rewriting
✔ Test validation
✔ PR description generation
✔ Guardrails against unsafe large rewrites

---

## ⚠ Current Limitations

* Monorepo environments may require custom test bootstrapping
* Complex UI/type-only issues are harder than pure logic bugs
* Large infra repos require advanced dependency resolution
* No semantic test failure reasoning yet (string-based)

---

## 🎯 Design Philosophy

This agent prioritizes:

1. Safety over aggressiveness
2. Controlled modification
3. Test-driven validation
4. Prevention of destructive rewrites
5. Reproducible local execution

---

## 📌 Roadmap

* [ ] Structured test-failure parsing
* [ ] Improved semantic ranking (AST-based)
* [ ] Smarter retry strategy
* [ ] Monorepo-aware test bootstrapping
* [ ] Benchmark repository for controlled evaluation
* [ ] SWE-bench style evaluation metrics

---

## 🧪 Running the Agent

```bash
python main.py
```

You will be prompted for:

* Repo Owner
* Repo Name
* Issue Number

---

## 📊 Research Direction

This project explores:

* Automated code repair
* LLM-guided refactoring
* Hybrid search + ranking
* Safe AI-assisted patch generation

---

## 📜 License

MIT License

Copyright (c) 2026 Tendulkar Mahadevan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


```

---