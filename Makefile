# Agentic EO hackathon: shortcuts for your MCP server.
#   make run      start the example server over HTTP on http://localhost:8000/mcp
#   make test     run examples/geocode-server/test.py (if present)
#   make check    run the registry's PR checks on SERVER_DIR (same as the registry CI)
#   make submit   open a pull request to eve-esa/mcp-tool-registry   (needs SERVER_NAME=...)

SHELL        := /bin/bash
# The lab kernel's Python (has mcp, ruff, ...); falls back to python3 elsewhere.
LAB_PYTHON   := $(HOME)/.venvs/agentic-eo/bin/python
PYTHON       ?= $(if $(wildcard $(LAB_PYTHON)),$(LAB_PYTHON),$(shell command -v python3 || command -v python))
REGISTRY_DIR ?= $(HOME)/mcp-tool-registry
REGISTRY     ?= eve-esa/mcp-tool-registry
SERVER_DIR   ?= examples/geocode-server
SERVER_NAME  ?=
PARTICIPANT  ?= $(shell grep -s '^PARTICIPANT=' .env | cut -d= -f2)
LABEL        ?= agentic-eo-berlin

.PHONY: help run test check submit _require-name

help:
	@sed -n '1,6p' Makefile

run:
	cd $(SERVER_DIR) && $(PYTHON) server.py --transport http

test:
	@if [[ ! -f "$(SERVER_DIR)/test.py" ]]; then \
		echo "No test.py in $(SERVER_DIR). Add one before make test, or set SERVER_DIR=."; exit 1; fi
	cd $(SERVER_DIR) && $(PYTHON) test.py

_require-name:
	@if [[ -z "$(SERVER_NAME)" ]]; then \
		echo "Give your server a name, e.g.:  make $(MAKECMDGOALS) SERVER_NAME=flood-watch"; exit 1; fi
	@if [[ ! "$(SERVER_NAME)" =~ ^[a-z][a-z0-9_-]{2,39}$$ ]]; then \
		echo "SERVER_NAME must be 3-40 chars: lowercase letters, digits, '-' or '_', starting with a letter."; exit 1; fi

# Stage SERVER_DIR as servers/<name>/ in a temp dir and run the registry's validate_pr.py there,
# exactly like the registry CI does for a pull request.
check:
	@if [[ ! -f "$(REGISTRY_DIR)/scripts/validate_pr.py" ]]; then \
		echo "Registry not found at $(REGISTRY_DIR). Clone it: git clone https://github.com/$(REGISTRY) $(REGISTRY_DIR)"; exit 1; fi
	@name="$${SERVER_NAME:-my-server}"; tmp=$$(mktemp -d); \
	mkdir -p "$$tmp/servers/$$name"; \
	rsync -a --exclude '.env' --exclude '__pycache__' --exclude '.ipynb_checkpoints' $(SERVER_DIR)/ "$$tmp/servers/$$name/"; \
	cp -f "$(REGISTRY_DIR)/ruff.toml" "$$tmp/" 2>/dev/null || true; \
	files=$$(cd "$$tmp" && find servers -type f | sort); \
	echo "Checking servers/$$name ($$(echo $$files | wc -w | tr -d ' ') files) with the registry rules..."; \
	cd "$$tmp" && PATH="$(dir $(PYTHON)):$$PATH" $(PYTHON) "$(REGISTRY_DIR)/scripts/validate_pr.py" --files $$files; \
	status=$$?; rm -rf "$$tmp"; exit $$status

# Fork the registry, add SERVER_DIR as servers/<SERVER_NAME>, push a branch and open a PR.
submit: _require-name
	@command -v gh >/dev/null || { echo "GitHub CLI (gh) is not installed. Ask a mentor."; exit 1; }
	@gh auth status >/dev/null 2>&1 || gh auth login --hostname github.com --git-protocol https --web
	@$(MAKE) --no-print-directory check SERVER_NAME=$(SERVER_NAME)
	@set -euo pipefail; \
	user=$$(gh api user --jq .login); \
	branch="hackathon/$${PARTICIPANT:-$$user}-$(SERVER_NAME)"; \
	tmp=$$(mktemp -d); \
	echo "Forking $(REGISTRY) to $$user (if not already forked)..."; \
	gh repo fork $(REGISTRY) --clone=false >/dev/null 2>&1 || true; \
	gh repo clone "$$user/$$(basename $(REGISTRY))" "$$tmp/registry" -- --depth 1 -q; \
	cd "$$tmp/registry"; \
	git remote add upstream "https://github.com/$(REGISTRY).git" 2>/dev/null || true; \
	git fetch -q --depth 1 upstream main; \
	git switch -q -c "$$branch" upstream/main; \
	if [[ -e "servers/$(SERVER_NAME)" ]]; then echo "servers/$(SERVER_NAME) already exists in the registry: pick another SERVER_NAME."; exit 1; fi; \
	mkdir -p "servers/$(SERVER_NAME)"; \
	rsync -a --exclude '.env' --exclude '__pycache__' --exclude '.ipynb_checkpoints' "$(CURDIR)/$(SERVER_DIR)/" "servers/$(SERVER_NAME)/"; \
	git add "servers/$(SERVER_NAME)"; \
	git -c user.name="$$(gh api user --jq '.name // .login')" -c user.email="$$user@users.noreply.github.com" \
		commit -q -m "Add $(SERVER_NAME) MCP server (Agentic EO hackathon, Berlin 2026)"; \
	gh auth setup-git >/dev/null 2>&1 || true; \
	git push -q -u origin "$$branch"; \
	label=""; gh label list -R $(REGISTRY) --search "$(LABEL)" --json name --jq '.[].name' 2>/dev/null | grep -qx "$(LABEL)" && label="--label $(LABEL)"; \
	gh pr create -R $(REGISTRY) --head "$$user:$$branch" --base main $$label \
		--title "Add $(SERVER_NAME) MCP server (Agentic EO hackathon)" \
		--body-file "$(CURDIR)/.github/PR_TEMPLATE.md"; \
	rm -rf "$$tmp"
