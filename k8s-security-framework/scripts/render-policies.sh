#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
environment=${1:-}
[[ $environment =~ ^(development|staging|production)$ ]] || { echo "usage: $0 development|staging|production" >&2; exit 2; }

"$project_dir/scripts/validate-policy-config.sh"
env_file="$project_dir/environments/$environment/parameters.env"
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

key_path="$project_dir/$COSIGN_PUBLIC_KEY_FILE"
if [[ $environment == production ]]; then
  [[ $APPROVED_REGISTRIES != *example.com* ]] || { echo "ERROR: production registry placeholder remains" >&2; exit 1; }
  [[ -f $key_path ]] || { echo "ERROR: production Cosign public key is missing: $key_path" >&2; exit 1; }
  ! grep -q 'PRIVATE KEY' "$key_path" || { echo "ERROR: private key must not be stored in repository" >&2; exit 1; }
fi

output_dir="$project_dir/artifacts/policies/$environment/$PROFILE"
mkdir -p "$output_dir"
find "$output_dir" -maxdepth 1 -type f -name 'KSP-*.yaml' -delete

cat > "$output_dir/render-metadata.env" <<EOF
ENVIRONMENT=$ENVIRONMENT
PROFILE=$PROFILE
APPROVED_REGISTRIES=$APPROVED_REGISTRIES
SIGNED_IMAGE_PATTERNS=$SIGNED_IMAGE_PATTERNS
COSIGN_PUBLIC_KEY_FILE=$COSIGN_PUBLIC_KEY_FILE
OWNER_LABEL_KEY=$OWNER_LABEL_KEY
ENVIRONMENT_LABEL_KEY=$ENVIRONMENT_LABEL_KEY
EXCLUDED_NAMESPACES=$EXCLUDED_NAMESPACES
AUDIT_MIN_DAYS=$AUDIT_MIN_DAYS
MAX_VIOLATION_RATE=$MAX_VIOLATION_RATE
MAX_FALSE_POSITIVE_RATE=$MAX_FALSE_POSITIVE_RATE
MAX_EXCEPTION_RATE=$MAX_EXCEPTION_RATE
MAX_ADMISSION_P95_MS=$MAX_ADMISSION_P95_MS
MAX_WEBHOOK_ERROR_RATE=$MAX_WEBHOOK_ERROR_RATE
EOF

while IFS= read -r id; do
  source_file=$(find "$project_dir/policies" -mindepth 3 -maxdepth 3 -type f -name "$id-*.yaml" -print -quit)
  [[ -n $source_file ]] || { echo "ERROR: missing policy $id" >&2; exit 1; }
  output_file="$output_dir/$(basename "$source_file")"
  cp "$source_file" "$output_file"

  severity=$(sed -n 's/.*policies.kyverno.io\/severity: //p' "$source_file" | head -n1)
  policy_type=validate
  grep -q '^      verifyImages:$' "$source_file" && policy_type=verify
  grep -q '^      mutate:$' "$source_file" && policy_type=mutate
  grep -q '^      generate:$' "$source_file" && policy_type=generate

  mode=Audit
  failure_policy=$FAILURE_POLICY_DEFAULT
  [[ $severity == critical ]] && failure_policy=$FAILURE_POLICY_CRITICAL
  case "$environment:$policy_type:$severity" in
    development:validate:*|development:verify:*) mode=Audit ;;
    staging:validate:critical|staging:verify:critical) mode=Enforce ;;
    production:validate:critical|production:verify:critical) mode=Enforce ;;
    production:validate:high) mode=Enforce ;;
  esac

  sed -i -E "s/failurePolicy: (Fail|Ignore)/failurePolicy: $failure_policy/" "$output_file"
  if [[ $policy_type == validate || $policy_type == verify ]]; then
    sed -i -E "s/failureAction: (Audit|Enforce)/failureAction: $mode/" "$output_file"
  fi

  sed -i "s#harbor\.example\.com#${APPROVED_REGISTRIES%%,*}#g" "$output_file"
  sed -i "s#harbor\.staging\.example\.com#${APPROVED_REGISTRIES%%,*}#g" "$output_file"
  sed -i "s#harbor\.production\.example\.com#${APPROVED_REGISTRIES%%,*}#g" "$output_file"
  sed -i -E "s/timeoutSeconds: (10|30)/timeoutSeconds: $WEBHOOK_TIMEOUT_SECONDS/" "$output_file"

  case "$id" in
    KSP-META-002)
      sed -i "s#policies\.ksp\.io/owner#$OWNER_LABEL_KEY#g" "$output_file"
      ;;
    KSP-META-003)
      sed -i "s#policies\.ksp\.io/environment#$ENVIRONMENT_LABEL_KEY#g" "$output_file"
      ;;
    KSP-RES-005)
      sed -i -e "s/requests.cpu: \"4\"/requests.cpu: \"$QUOTA_REQUESTS_CPU\"/" \
        -e "s/requests.memory: 8Gi/requests.memory: $QUOTA_REQUESTS_MEMORY/" \
        -e "s/limits.cpu: \"8\"/limits.cpu: \"$QUOTA_LIMITS_CPU\"/" \
        -e "s/limits.memory: 16Gi/limits.memory: $QUOTA_LIMITS_MEMORY/" \
        -e "s/pods: \"50\"/pods: \"$QUOTA_PODS\"/" "$output_file"
      ;;
    KSP-RES-006)
      sed -i -e "s/defaultRequest: {cpu: 100m, memory: 128Mi}/defaultRequest: {cpu: $LIMIT_DEFAULT_REQUEST_CPU, memory: $LIMIT_DEFAULT_REQUEST_MEMORY}/" \
        -e "s/default: {cpu: 500m, memory: 512Mi}/default: {cpu: $LIMIT_DEFAULT_CPU, memory: $LIMIT_DEFAULT_MEMORY}/" \
        -e "s/min: {cpu: 25m, memory: 32Mi}/min: {cpu: $LIMIT_MIN_CPU, memory: $LIMIT_MIN_MEMORY}/" \
        -e "s/max: {cpu: \"2\", memory: 2Gi}/max: {cpu: \"$LIMIT_MAX_CPU\", memory: $LIMIT_MAX_MEMORY}/" "$output_file"
      ;;
    KSP-IMG-004)
      sed -i "s#harbor[^\"]*/*#${SIGNED_IMAGE_PATTERNS%%,*}#" "$output_file"
      if [[ -f $key_path ]]; then
        public_key=$(awk '{printf "%s\\n", $0}' "$key_path")
        PUBLIC_KEY_ESCAPED=$public_key perl -0pi -e 's#-----BEGIN PUBLIC KEY-----.*?-----END PUBLIC KEY-----#$ENV{PUBLIC_KEY_ESCAPED}#s' "$output_file"
      fi
      sed -i "s/timeoutSeconds: $WEBHOOK_TIMEOUT_SECONDS/timeoutSeconds: $VERIFY_IMAGE_TIMEOUT_SECONDS/" "$output_file"
      ;;
  esac
done < "$project_dir/profiles/$PROFILE/policy-ids.txt"

cat > "$output_dir/namespace-exclusions.yaml" <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: ksp-policy-render-settings
  namespace: kyverno
  labels:
    app.kubernetes.io/managed-by: ksp-policy-renderer
data:
  environment: "$ENVIRONMENT"
  profile: "$PROFILE"
  excludedNamespaces: "$EXCLUDED_NAMESPACES"
EOF

echo "Rendered $(find "$output_dir" -type f -name 'KSP-*.yaml' | wc -l) policies to $output_dir"
