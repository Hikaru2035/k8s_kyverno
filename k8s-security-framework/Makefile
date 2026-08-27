.PHONY: help bootstrap install test verify uninstall policy-validate policy-render policy-render-all

help:
	@echo "Targets: bootstrap install test verify uninstall policy-validate policy-render policy-render-all"

bootstrap install test verify uninstall:
	@echo "TODO: implement target '$@'"

policy-validate:
	@./scripts/validate-policy-config.sh

policy-render:
	@test -n "$(ENVIRONMENT)" || { echo "ENVIRONMENT is required"; exit 2; }
	@./scripts/render-policies.sh "$(ENVIRONMENT)"

policy-render-all:
	@./scripts/render-policies.sh development
	@./scripts/render-policies.sh staging
	@./scripts/render-policies.sh production
