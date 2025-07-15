# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Essential Commands
- `script/setup` - Complete development environment setup (creates venv, installs dependencies, configures pre-commit)
- `script/bootstrap` - Install core dependencies and prepare development environment
- `script/lint` - Run linting on changed files (ruff + pylint)
- `script/server` - Start Home Assistant development server
- `pytest tests/` - Run test suite (use `pytest tests/components/DOMAIN/` for specific integration tests)
- `pre-commit run --all-files` - Run all pre-commit hooks

### Linting and Type Checking
- `ruff check .` - Fast Python linting
- `pylint homeassistant/` - Comprehensive Python linting
- `mypy homeassistant/` - Type checking
- `script/check_format` - Check code formatting
- `script/check_dirty` - Check for uncommitted changes

### Testing
- `pytest tests/components/DOMAIN/` - Test specific integration
- `pytest tests/test_FILE.py::test_function` - Run specific test
- `script/split_tests.py` - Utility for splitting test runs

## Architecture Overview

### Core Structure
Home Assistant is built around these fundamental concepts:
- **Core (`homeassistant/core.py`)** - Central state machine with `HomeAssistant` class managing entities, events, and services
- **Components (`homeassistant/components/`)** - Modular integrations for devices/services (1000+ integrations)
- **Helpers (`homeassistant/helpers/`)** - Shared utilities for entity management, config flows, coordinators
- **Configuration** - YAML-based configuration with config entry flows for UI-based setup

### Key Directories
- `homeassistant/components/DOMAIN/` - Integration implementations
  - `manifest.json` - Integration metadata and dependencies
  - `config_flow.py` - UI configuration flow
  - `coordinator.py` - Data update coordination
  - `PLATFORM.py` - Platform implementations (sensor, switch, etc.)
- `homeassistant/helpers/` - Framework utilities (entity registry, device registry, update coordinators)
- `homeassistant/auth/` - Authentication and authorization system
- `tests/components/DOMAIN/` - Integration tests

### Integration Patterns
- **Config Entry Pattern** - Modern integrations use config entries for UI-based setup
- **Update Coordinator Pattern** - Centralized data fetching with `DataUpdateCoordinator`
- **Entity Pattern** - All devices expose entities (sensors, switches, etc.) extending base entity classes
- **Platform Architecture** - Integrations implement specific platforms (sensor, binary_sensor, switch, etc.)

## Python Standards

### Requirements
- Python 3.13+ compatibility required
- Use modern Python features: dataclasses, type hints, f-strings, pattern matching, walrus operator
- All external I/O must be async
- Follow async patterns: avoid sleeping in loops, use gather() instead of awaiting in loops

### Code Quality
- **Formatting**: Ruff (configured in pyproject.toml)
- **Linting**: PyLint + Ruff with extensive rule configuration
- **Type Checking**: MyPy with strict typing
- **Testing**: pytest with fixtures from `tests.common`

### Integration Development
- Use `homeassistant/const.py` constants instead of hardcoding strings
- Follow update coordinator pattern for polling (minimum 5s local, 60s cloud)
- Implement proper error handling with specific exceptions from `homeassistant.exceptions`
- Entity unique IDs must be stable (use serial numbers/MAC addresses, not IP/hostnames)
- Use lazy logging with parameters, not f-strings in log messages

### File Conventions
- **Constants**: `const.py`
- **Models**: `models.py` 
- **Coordinator**: `coordinator.py`
- **Config Flow**: `config_flow.py`
- **Platforms**: `{platform}.py` (sensor.py, switch.py, etc.)

## Testing Guidelines
- Tests located in `tests/components/DOMAIN/`
- Use pytest fixtures from `tests.common`
- Mock external dependencies
- Use snapshots for complex data validation
- Follow existing test patterns in similar integrations