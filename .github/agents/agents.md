# Python Development Guidelines

This repository follows strict Python development standards for production-quality code.

## Available Agents

We use two specialized AI agents to maintain code quality:

### Python-Assistant (Development Helper)
Use for: Writing new features, learning patterns, getting guidance
- Friendly and educational approach
- Provides complete working examples
- Explains design decisions
- Helps you understand best practices

### Code-Quality-Enforcer (Critical Reviewer)
Use for: Code reviews, refactoring, enforcing standards
- Strict enforcement of all quality guidelines
- Identifies anti-patterns and technical debt
- Demands production-level code
- Zero tolerance for quality issues

**Workflow:** Write code with Python-Assistant, review it with Code-Quality-Enforcer.

---

## Core Principles

**Clarity over cleverness**: Write code humans can understand at first glance.

**Lean and focused**: Single responsibility, minimal dependencies, no premature optimization.

**Testable by design**: Pure functions, dependency injection, clear separation of concerns.

## Python Style

- Follow standard Python conventions (PEP 8) and the Zen of Python.
- Prefer small, focused functions and classes with a single responsibility.
- Avoid unnecessary abstractions, inheritance, or patterns unless they clearly reduce duplication or clarify intent.
- Keep public APIs minimal and well named; choose descriptive, concise identifiers.

## Design Principles

- Apply DRY and KISS: remove duplication and avoid overengineering.
- Bias toward pure functions and explicit data flow where feasible.
- Separate concerns: keep business logic separate from I/O, configuration, and infrastructure.
- Write code that is easy to test; prefer dependency injection over hard-coded globals.

## Code Organization (Mandatory)

Every Python module must follow this structure:

1. **Module docstring** (recommended for non-trivial modules)
2. **Imports** (stdlib → third-party → local, separated by blank lines)
3. **Constants** (UPPER_CASE naming, grouped with section headers)
4. **Exception classes** (inherit from Exception or appropriate base)
5. **Classes** (if any, with proper initialization and encapsulation)
6. **Functions** (grouped by responsibility with section comments):
   ```python
   # ========== HTTP & PARSING HELPERS ==========
   # ========== DEVICE OPERATIONS ==========
   # ========== CONFIG MANAGEMENT ==========
   # ========== DISPLAY HELPERS ==========
   # ========== ESTIMATION LOGIC ==========
   # ========== LOGGING ==========
   # ========== MAIN CONTROL LOOP ==========
   ```
7. **Entry point** (`if __name__ == "__main__"`)

## Testing and Documentation

- When adding non-trivial logic, also propose or update unit tests.
- Prefer short, focused docstrings that explain "why" and any non-obvious behavior.
- Keep comments high-signal; do not restate what the code clearly shows.
- Use type hints for function parameters and return values.

## Refactoring Behavior

- When refactoring, preserve behavior and public APIs unless explicitly asked to change them.
- Prefer incremental, safe refactorings over large, risky rewrites.
- Keep tests passing after each change.

## Quality Checklist

Before committing code, verify:

- [ ] Functions < 50 lines, focused on single responsibility
- [ ] No magic numbers (all values are named constants)
- [ ] Descriptive variable names (no cryptic abbreviations)
- [ ] Type hints on parameters and returns
- [ ] Docstrings for all public functions/classes
- [ ] Specific exception handling (no bare `except`)
- [ ] Unit tests for non-trivial logic
- [ ] Proper file structure with section headers
- [ ] No duplicate code (DRY principle applied)
- [ ] Code reviewed by Code-Quality-Enforcer agent
