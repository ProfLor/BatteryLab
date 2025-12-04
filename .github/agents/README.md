# Development Agents

This repository uses specialized AI agents to maintain code quality.

## Available Agents

### 1. Python-Assistant (Friendly Helper)
**Use when:** Writing new code, learning best practices, getting explanations
**Personality:** Friendly, educational, practical
**Focus:** Helps you write clean code with guidance and complete examples

### 2. Code-Quality-Enforcer (Critical Expert)
**Use when:** Code review, refactoring, enforcing standards
**Personality:** Strict, detailed, uncompromising
**Focus:** Identifies ALL quality issues and demands production-level code

## Project Standards

### Code Quality Principles
- **Clarity over cleverness**: Write code humans understand at first glance
- **Lean and focused**: Single responsibility, minimal dependencies, no premature optimization
- **Testable by design**: Pure functions, dependency injection, clear separation of concerns

### Python Standards
- Follow PEP 8 and the Zen of Python
- DRY (Don't Repeat Yourself) and KISS (Keep It Simple)
- Explicit over implicit, simple over complex
- Type hints for all public APIs

### Mandatory File Structure
1. Module docstring (for non-trivial modules)
2. Imports: stdlib → third-party → local (blank line separated)
3. Constants: UPPER_CASE, grouped with section headers
4. Exceptions: Custom classes at top
5. Classes: Proper encapsulation
6. Functions: Grouped by domain with headers (# ========== SECTION ==========)
7. Entry point: if __name__ == "__main__"

### Quality Checklist
- [ ] Functions < 50 lines, single responsibility
- [ ] No magic numbers (use named constants)
- [ ] Descriptive names (no cryptic abbreviations)
- [ ] Type hints on parameters and returns
- [ ] Docstrings for all public APIs
- [ ] Specific exception handling (no bare except)
- [ ] Unit tests for non-trivial logic
- [ ] Proper file structure with section headers

### When to Use Which Agent
- **Starting new features?** → Use Python-Assistant for guidance
- **Code review time?** → Use Code-Quality-Enforcer for thorough critique
- **Learning best practices?** → Use Python-Assistant for explanations
- **Enforcing standards?** → Use Code-Quality-Enforcer for strict enforcement
- **Refactoring legacy code?** → Use Code-Quality-Enforcer to identify all issues

**Recommended Workflow:** Write with Python-Assistant → Review with Code-Quality-Enforcer
