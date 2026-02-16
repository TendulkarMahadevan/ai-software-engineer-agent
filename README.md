## 🤖 AI Software Engineer Agent (CLI)

Autonomous AI-powered CLI system that analyzes GitHub issues, explores repositories, generates validated code fixes, and automates Git workflows with safety guardrails.

---

## 🚀 Overview

This project simulates an AI Software Engineer capable of:

1. Reading GitHub issues
2. Analyzing repository structure
3. Identifying relevant files
4. Generating constrained patch proposals
5. Validating modifications against hallucinated edits
6. Automating Git branch creation and commits

Built with a production-minded architecture focusing on reliability, safety, and deterministic behavior.

---

## 🏗️ Architecture

```
GitHub Issue
      ↓
Repo Search Tool
      ↓
Context Extraction
      ↓
LLM Patch Generator
      ↓
Diff Validation Layer
      ↓
Git Automation Engine
```

---

## 🧠 Key Features Implemented

### 🔹 GitHub Integration

* Fetches issue metadata and content
* Retrieves repository tree and file content
* Handles API failures and 404 errors safely

### 🔹 Intelligent Repository Search

* Filters relevant files by keyword
* Avoids binary files
* Limits search scope for precision

### 🔹 Context-Aware Patch Generation

* Deterministic LLM calls (temperature=0)
* Explicit file path constraints
* Unified diff generation

### 🔹 Diff Validation Layer (Production Hardening v1)

* Extracts modified file paths
* Blocks unauthorized file edits
* Prevents hallucinated patches

### 🔹 API Reliability Layer

* Automatic retry handling for rate limits
* Controlled failure behavior

### 🔹 Git Automation Engine (Production Hardening v2)

* Clones repository into isolated temp directory
* Creates feature branch automatically
* Applies AI-generated patch
* Commits changes programmatically
* Generates local git diff for verification

---

## 🛡 Production Safety Design

* No direct modification of original repositories
* All operations performed in isolated environment
* File modification restricted to validated paths
* Deterministic patch generation

---

## 🧩 Tech Stack

* Python
* OpenAI API
* GitHub REST API
* GitPython
* Modular tool-based architecture

---

## 📌 Current Status

Early Production-Grade MVP
– Patch validation enabled
– Git automation enabled
– PR description generation enabled

Next planned improvements:

* Full file rewrite mode
* PR auto-creation
* Multi-file patch support
* Reflection loop
* Autonomous tool reasoning
