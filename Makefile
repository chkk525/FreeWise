.PHONY: help install test test-quick lint deploy bench dev clean

PYTHON ?= uv run python
PYTEST ?= uv run pytest

help:
	@echo "Targets:"
	@echo "  install   sync dependencies (uv sync)"
	@echo "  test      run the full pytest suite (~3s)"
	@echo "  test-quick run a subset for fast feedback (kindle + api_v2 only)"
	@echo "  lint      ruff + type check (best-effort)"
	@echo "  dev       start the FastAPI app at :8000 with auto-reload"
	@echo "  deploy    rsync this worktree to QNAP and rebuild the freewise container"
	@echo "  bench     curl-time the production endpoints on 192.168.0.171"
	@echo "  clean     remove __pycache__ + .pytest_cache"

install:
	uv sync

test:
	$(PYTEST) -q

test-quick:
	$(PYTEST) -q tests/services/ tests/importers/ tests/test_db_migrations.py tests/api_v2/

lint:
	-uv run ruff check app/ tests/

dev:
	$(PYTHON) -m uvicorn app.main:app --reload --port 8000

deploy:
	@if [ ! -d $(HOME)/Development/freewise-qnap-deploy ]; then \
		echo "ERROR: ~/Development/freewise-qnap-deploy worktree missing — checkout first"; exit 1; \
	fi
	LOCAL_SRC=$(CURDIR) bash $(HOME)/Development/freewise-qnap-deploy/tools/deploy_qnap.sh

bench:
	@for p in /dashboard/ui /library/ui /highlights/ui/review /highlights/ui/favorites /import/api-token /api/v2/auth/ /dashboard/kindle/status; do \
		printf "%-35s" "$$p"; \
		for i in 1 2 3; do \
			t=$$(/usr/bin/curl -sL -o /dev/null -w '%{time_total}' "http://192.168.0.171:8063$$p"); \
			c=$$(/usr/bin/curl -sL -o /dev/null -w '%{http_code}' "http://192.168.0.171:8063$$p"); \
			printf "  %s/%ss" "$$c" "$$t"; \
		done; \
		printf "\n"; \
	done

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
