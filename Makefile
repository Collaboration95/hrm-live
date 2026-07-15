PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
MPLCONFIGDIR ?= /tmp/hrm-live-matplotlib
APP_BUNDLE := dist/HRM Live.app
COMPILE_PATHS := src tests setup.py

.PHONY: help venv install run format format-check lint typecheck test test-verbose coverage compile check build verify-bundle package clean

help:
	@printf "HRM Live development targets:\n"
	@printf "  make venv           Create .venv with python3\n"
	@printf "  make install        Install app and dev dependencies into .venv\n"
	@printf "  make run            Run the menu bar app in dev mode\n"
	@printf "  make format-check   Check formatting with Ruff\n"
	@printf "  make lint           Run Ruff lint\n"
	@printf "  make typecheck      Run mypy\n"
	@printf "  make test           Run the pytest suite\n"
	@printf "  make coverage       Run tests with coverage threshold\n"
	@printf "  make test-verbose   Run the pytest suite with verbose output\n"
	@printf "  make compile        Compile-check Python modules\n"
	@printf "  make check          Run tests and compile-checks\n"
	@printf "  make build          Build dist/HRM Live.app with py2app\n"
	@printf "  make verify-bundle  Verify built app signing and Info.plist metadata\n"
	@printf "  make package        Build and verify the app bundle\n"
	@printf "  make clean          Remove generated build/test artifacts\n"

venv:
	python3 -m venv .venv

install:
	$(PIP) install -e ".[dev,build]"

run:
	$(PYTHON) -m hrm_live

format:
	$(PYTHON) -m ruff format src tests setup.py

format-check:
	$(PYTHON) -m ruff format --check src tests setup.py

lint:
	$(PYTHON) -m ruff check src tests setup.py

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

test-verbose:
	$(PYTHON) -m pytest -v

coverage:
	$(PYTHON) -m pytest --cov --cov-report=term-missing

compile:
	$(PYTHON) -m compileall $(COMPILE_PATHS)

check: format-check lint typecheck test coverage compile

build:
	@mkdir -p "$(MPLCONFIGDIR)"
	MPLCONFIGDIR="$(MPLCONFIGDIR)" $(PYTHON) setup.py py2app

verify-bundle:
	@test -d "$(APP_BUNDLE)" || (printf "Missing app bundle: $(APP_BUNDLE)\n" >&2; exit 1)
	codesign --verify --deep --strict "$(APP_BUNDLE)"
	codesign -d --entitlements :- "$(APP_BUNDLE)"
	/usr/libexec/PlistBuddy -c "Print :LSUIElement" "$(APP_BUNDLE)/Contents/Info.plist"
	/usr/libexec/PlistBuddy -c "Print :NSBluetoothAlwaysUsageDescription" "$(APP_BUNDLE)/Contents/Info.plist"
	/usr/libexec/PlistBuddy -c "Print :NSBluetoothPeripheralUsageDescription" "$(APP_BUNDLE)/Contents/Info.plist"

package: build verify-bundle

clean:
	rm -rf build dist .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
