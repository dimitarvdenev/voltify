PYTHON := .venv/bin/python
HOST := 127.0.0.1
PORT := 8000
URL := http://localhost:$(PORT)/ui/index.html
TMPDIR ?= /tmp
MPLCONFIGDIR ?= $(TMPDIR)/mpl

.PHONY: demo ui agent test clean-run check-port

demo: check-port clean-run
	@mkdir -p "$(MPLCONFIGDIR)"
	@echo "Starting UI at $(URL)"
	@HOST="$(HOST)" PORT="$(PORT)" MPLCONFIGDIR="$(MPLCONFIGDIR)" $(PYTHON) ui/serve.py & \
	server_pid=$$!; \
	trap 'echo ""; echo "Stopping UI server"; kill $$server_pid 2>/dev/null || true; wait $$server_pid 2>/dev/null || true' INT TERM EXIT; \
	sleep 1; \
	echo "Open $(URL)"; \
	echo "Starting agent in inbox mode. Use the web input to talk to it."; \
	MPLCONFIGDIR="$(MPLCONFIGDIR)" $(PYTHON) -m agent.main --inbox

ui:
	@mkdir -p "$(MPLCONFIGDIR)"
	@echo "Serving $(URL)"
	@HOST="$(HOST)" PORT="$(PORT)" MPLCONFIGDIR="$(MPLCONFIGDIR)" $(PYTHON) ui/serve.py

agent:
	@mkdir -p "$(MPLCONFIGDIR)"
	@MPLCONFIGDIR="$(MPLCONFIGDIR)" $(PYTHON) -m agent.main --inbox

test:
	@MPLCONFIGDIR="$(MPLCONFIGDIR)" $(PYTHON) -m pytest tests/ -v

clean-run:
	@rm -rf artifacts/run

check-port:
	@if lsof -iTCP:$(PORT) -sTCP:LISTEN -t >/dev/null 2>&1; then \
		echo "Port $(PORT) is already in use. Stop the existing server or run 'make ui PORT=8001'."; \
		exit 1; \
	fi
