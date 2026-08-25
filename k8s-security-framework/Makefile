.PHONY: help bootstrap install test verify uninstall policy-validate policy-render

help:
	@echo "Targets: bootstrap install test verify uninstall policy-validate policy-render"

bootstrap install test verify uninstall:
	@echo "TODO: implement target '$@'"

policy-validate:
	@./scripts/validate-policy-config.sh

policy-render:
	@test -n "$(ENVIRONMENT)" || { echo "ENVIRONMENT is required"; exit 2; }
	@./scripts/render-policies.sh "$(ENVIRONMENT)"
