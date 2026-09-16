REPO_ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
FRAMEWORK_ROOT := $(REPO_ROOT)k8s-security-framework

.PHONY: help bootstrap install test verify uninstall policy-validate policy-render policy-render-all

help:
	@echo "Targets: bootstrap install test verify uninstall policy-validate policy-render policy-render-all"

bootstrap install test verify uninstall:
	@echo "TODO: implement target '$@'"

policy-validate:
	@bash "$(FRAMEWORK_ROOT)/scripts/validate-policy-config.sh"

policy-render:
	@test -n "$(ENVIRONMENT)" || { echo "ENVIRONMENT is required"; exit 2; }
	@bash "$(FRAMEWORK_ROOT)/scripts/render-policies.sh" "$(ENVIRONMENT)"

policy-render-all:
	@bash "$(FRAMEWORK_ROOT)/scripts/render-policies.sh" development
	@bash "$(FRAMEWORK_ROOT)/scripts/render-policies.sh" staging
	@bash "$(FRAMEWORK_ROOT)/scripts/render-policies.sh" production
